// Moteur efibuild porte en JavaScript. Meme regles que efibuilder/*.py,
// limitees a ce qui est calculable sans reseau ni acces disque.
function makeEngine(DATA) {
  const versions = DATA.macos.versions;
  const vIndex = k => versions.findIndex(v => v.key === k);

  function resolve(profile) {
    const plat = DATA.platforms.platforms.find(p => p.id === profile.platform);
    const macos = versions.find(v => v.key === profile.macos);
    const laptop = profile.chassis
      ? profile.chassis === "laptop"
      : (plat.default_chassis ? plat.default_chassis === "laptop"
                              : plat.family === "intel-laptop");
    const digits = (profile.chipset || "").match(/(\d+)/);
    let series = "";
    if (digits) {
      const d = digits[1];
      series = d.length === 2 ? d[0] : (d.length === 3 ? d[0] + "00" : d);
    }
    return {
      ...profile, plat, macos, laptop,
      family: plat.family,
      darwin: macos.darwin,
      chipset_series: series,
      smbios_model: profile.smbios || plat.smbios.default,
    };
  }

  function field(ctx, name) {
    if (name in ctx) return ctx[name];
    throw new Error("champ inconnu: " + name);
  }

  function matches(ctx, cond) {
    if (!cond) return true;
    if (cond.any) return cond.any.some(c => matches(ctx, c));
    if (cond.all) return cond.all.every(c => matches(ctx, c));
    if (cond.not) return !matches(ctx, cond.not);
    const value = field(ctx, cond.field);
    if ("eq" in cond) return value === cond.eq;
    if ("in" in cond) {
      if (typeof value === "string") {
        return cond.in.map(v => String(v).toLowerCase()).includes(value.toLowerCase());
      }
      return cond.in.includes(value);
    }
    if ("contains" in cond) return (value || []).includes(cond.contains);
    throw new Error("condition mal formee");
  }

  const ssdts = ctx => (ctx.plat.ssdt || []).filter(s => matches(ctx, s.when));

  function kexts(ctx) {
    const chosen = [], warnings = [];
    for (const entry of DATA.kexts.kexts) {
      if (!entry.required && !matches(ctx, entry.when)) continue;
      if (entry.min_darwin && ctx.darwin < entry.min_darwin) continue;
      if (entry.max_darwin && ctx.darwin > entry.max_darwin) continue;
      if (entry.max_macos && vIndex(ctx.macos.key) > vIndex(entry.max_macos)) {
        warnings.push(`${entry.id} n'est pas supporte au-dela de ` +
          `${versions[vIndex(entry.max_macos)].name}: non installe.`);
        continue;
      }
      const note = (entry.warn_macos || {})[ctx.macos.key];
      if (note) warnings.push(`${entry.id}: ${note}`);
      chosen.push(entry);
    }
    if (ctx.ethernet === "auto") {
      warnings.push("carte Ethernet non precisee: aucun pilote reseau installe.");
    }
    chosen.sort((a, b) => (a.order ?? 100) - (b.order ?? 100));
    return { chosen, warnings };
  }

  function quirks(ctx) {
    const out = {};
    for (const [section, values] of Object.entries(ctx.plat.quirks || {})) {
      for (let [key, expected] of Object.entries(values)) {
        if (expected && typeof expected === "object" && "value" in expected) {
          if (!matches(ctx, expected.when)) continue;
          expected = expected.value;
        }
        let target = section;
        if (key === "DummyPowerManagement") target = "Kernel -> Emulate";
        if (key === "XhciPortLimit" && ctx.darwin >= 20) expected = false;
        out[`${target}.${key}`] = expected;
      }
    }
    return out;
  }

  function bootArgs(ctx) {
    const args = [];
    if (ctx.debug) args.push("-v", "debug=0x100", "keepsyms=1");
    args.push(...(ctx.plat.boot_args || []));
    if (ctx.audio !== "none") args.push(`alcid=${ctx.audio_layout}`);
    if (ctx.dgpu === "amd-navi") args.push("agdpmod=pikera");
    if (ctx.dgpu === "nvidia-unsupported") args.push("-wegnoegpu");
    if (ctx.features.includes("ota") && ctx.darwin >= 23) args.push("revpatch=sbvmm");
    if (ctx.bluetooth === "intel" && ctx.darwin >= 25) args.push("-ibtcompatbeta");
    if (ctx.features.includes("no-avx2")) args.push("-nokcmismatchpanic");
    if (ctx.features.includes("i2c-polling")) args.push("-vi2c-force-polling");
    return args;
  }

  function releaseTuple(value) {
    const parts = (value.match(/\d+/g) || []).map(Number);
    return parts[0] === 10 ? parts.slice(0, 2) : parts.slice(0, 1);
  }

  function smbiosServes(model, macosEntry) {
    const ref = DATA.smbios.models.find(m => m.model.toLowerCase() === model.toLowerCase());
    if (!ref) return { known: false };
    const served = DATA.boards.boards[ref.board_id];
    if (served === undefined) return { known: true, ref, ok: null };
    if (served === "latest") return { known: true, ref, ok: true, served };
    const a = releaseTuple(served), b = releaseTuple(macosEntry.release);
    const ok = a[0] > b[0] || (a[0] === b[0] && (a[1] ?? 0) >= (b[1] ?? 0));
    return { known: true, ref, ok, served };
  }

  function blockers(ctx) {
    const out = [];
    if (ctx.macos.requires.includes("avx2") &&
        ["monterey", "high-sierra"].includes(ctx.plat.max_macos)) {
      out.push(`${ctx.macos.name} exige AVX2, absent de ${ctx.plat.name}.`);
    }
    return out;
  }

  function warnings(ctx) {
    const out = [];
    const idx = vIndex(ctx.macos.key);
    if (ctx.plat.max_macos && idx > vIndex(ctx.plat.max_macos)) {
      out.push(`${ctx.plat.name} n'est plus supporte au-dela de ` +
        `${versions[vIndex(ctx.plat.max_macos)].name} par le guide Dortania.`);
    }
    const sm = smbiosServes(ctx.smbios_model, ctx.macos);
    if (!sm.known) out.push(`SMBIOS ${ctx.smbios_model} absent de la table de reference.`);
    else if (sm.ok === false) {
      out.push(`le SMBIOS ${ctx.smbios_model} ne recoit pas ${ctx.macos.name}: les ` +
        `serveurs Apple s'arretent a macOS ${sm.served} pour ce board-id.`);
    }
    if (ctx.family === "amd" && ctx.cpu_cores <= 0) {
      out.push("nombre de coeurs inconnu: le patch AMD 'cpuid_cores_per_package' " +
        "restera sur sa valeur par defaut (option --cores).");
    }
    if (ctx.family === "amd" && ctx.laptop) {
      out.push("portable AMD: hors du perimetre du guide Dortania, mais la communaute " +
        "(AMD_Vanilla + NootedRed) fait tourner ces machines.");
    }
    if (ctx.igpu_mode === "display" && ctx.igpu === "none") {
      out.push("igpu_mode=display alors qu'aucun iGPU n'est declare.");
    }
    if (ctx.wifi === "realtek") {
      out.push("Wi-Fi Realtek PCIe: pas de pilote officiel, mais un portage " +
        "communautaire du pilote Linux rtw88 existe (Feixiao / RTL8821CEwifi).");
    }
    if (ctx.usb_map_kind === "none" && ctx.darwin >= 20) {
      out.push("aucun mappage USB: XhciPortLimit n'est plus fiable depuis macOS 11.3.");
    }
    return out;
  }

  return { resolve, matches, ssdts, kexts, quirks, bootArgs, blockers, warnings,
           smbiosServes, versions };
}
if (typeof module !== "undefined") module.exports = { makeEngine };
