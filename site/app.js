(function () {
  const engine = makeEngine(DATA);
  const $ = id => document.getElementById(id);
  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  };

  const FAMILIES = [
    ["intel-desktop", "Bureau Intel"],
    ["intel-laptop", "Portable Intel"],
    ["intel-hedt", "Station de travail Intel"],
    ["amd", "AMD"],
  ];
  const VENDORS = ["", "asus", "gigabyte", "msi", "asrock", "dell", "hp", "lenovo", "acer"];
  const DGPU = [
    ["none", "Aucune"], ["amd-polaris", "AMD Polaris (RX 400/500)"],
    ["amd-vega", "AMD Vega"], ["amd-navi", "AMD Navi (RX 5000)"],
    ["amd-rdna2", "AMD RDNA2 (RX 6000)"], ["amd-apu", "APU AMD (Vega intégré)"],
    ["nvidia-kepler", "NVIDIA Kepler"], ["nvidia-unsupported", "NVIDIA non supportée"],
  ];
  const ETHERNET = [
    ["auto", "Non précisée"], ["none", "Aucune"], ["intel-i219", "Intel I217/I218/I219"],
    ["intel-igb", "Intel I210/I211/I350"], ["intel-i225", "Intel I225 2,5 Gb"],
    ["rtl8111", "Realtek RTL8111/8168"], ["rtl8125", "Realtek RTL8125 2,5 Gb"],
    ["atheros", "Atheros / Killer E2200"],
  ];
  const WIFI = [["none", "Aucun"], ["intel", "Intel"], ["broadcom", "Broadcom"],
                ["realtek", "Realtek"], ["mediatek", "MediaTek"], ["qualcomm", "Qualcomm"]];
  const BT = [["none", "Aucun"], ["intel", "Intel"], ["broadcom", "Broadcom"],
              ["realtek", "Realtek"]];
  const TOUCHPAD = [["none", "Aucun"], ["ps2", "PS2"], ["i2c", "I2C"]];
  const FEATURES = [
    ["ota", "Mises à jour OTA"], ["gui", "Menu graphique"], ["sidecar", "Sidecar / AirPlay"],
    ["hibernation", "Hibernation"], ["custom-smbios", "SMBIOS en dur"],
    ["i2c-polling", "Trackpad en polling"], ["light-sensor", "Capteur de luminosité"],
    ["sata-legacy", "SATA non reconnu"], ["cpufriend", "Profil CPU"],
    ["rtc-fix", "Correctif RTC"], ["no-avx2", "CPU sans AVX2"],
    ["audio-chime", "Son de démarrage"], ["linux-boot", "Démarrer Linux"],
  ];

  function fill(select, pairs, value) {
    select.replaceChildren();
    for (const [v, label] of pairs) {
      const o = el("option", null, label);
      o.value = v;
      select.appendChild(o);
    }
    if (value !== undefined) select.value = value;
  }

  fill($("family"), FAMILIES, "intel-desktop");
  fill($("vendor"), VENDORS.map(v => [v, v ? v[0].toUpperCase() + v.slice(1) : "Non précisée"]));
  fill($("dgpu"), DGPU);
  fill($("ethernet"), ETHERNET);
  fill($("wifi"), WIFI);
  fill($("bluetooth"), BT);
  fill($("touchpad"), TOUCHPAD);
  fill($("macos"), engine.versions.slice(6).map(v => [v.key, `${v.name} — macOS ${v.release}`]),
       "sequoia");

  for (const [key, label] of FEATURES) {
    const wrap = el("label", "check");
    const box = document.createElement("input");
    box.type = "checkbox";
    box.value = key;
    box.checked = key === "ota";
    box.addEventListener("change", render);
    wrap.append(box, document.createTextNode(label));
    $("features").appendChild(wrap);
  }

  function platformsFor(family) {
    return DATA.platforms.platforms.filter(p => p.family === family);
  }

  function syncPlatforms(keep) {
    const list = platformsFor($("family").value);
    fill($("platform"), list.map(p => [p.id, p.name]), keep && list.some(p => p.id === keep)
      ? keep : list[0].id);
    syncSmbios();
  }

  let smbiosTouched = false;

  function syncSmbios() {
    const plat = DATA.platforms.platforms.find(p => p.id === $("platform").value);
    const recommended = plat.smbios.default;
    const others = (plat.smbios.alternatives || []);
    const rest = DATA.smbios.models.map(m => m.model)
      .filter(m => m !== recommended && !others.includes(m));
    const pairs = [[recommended, `${recommended} — recommandé`]]
      .concat(others.map(m => [m, `${m} — alternative`]))
      .concat(rest.map(m => [m, m]));
    // Le modele recommande suit la plateforme, sauf si l'utilisateur l'a choisi lui-meme.
    const previous = $("smbios").value;
    const keep = smbiosTouched && pairs.some(p => p[0] === previous);
    fill($("smbios"), pairs, keep ? previous : recommended);
  }

  function readProfile() {
    const igpuChoice = $("igpu").value;
    const features = [...$("features").querySelectorAll("input:checked")].map(b => b.value);
    return {
      platform: $("platform").value, macos: $("macos").value, chassis: "",
      chipset: $("chipset").value.trim(), motherboard_vendor: $("vendor").value,
      cpu_cores: Number($("cores").value) || 0,
      igpu: igpuChoice === "none" ? "none" : "igpu",
      igpu_mode: igpuChoice === "none" ? "none" : igpuChoice,
      igpu_variant: "", dgpu: $("dgpu").value, audio: "alc",
      audio_layout: Number($("alcid").value) || 1,
      ethernet: $("ethernet").value, wifi: $("wifi").value, bluetooth: $("bluetooth").value,
      touchpad: $("touchpad").value, nvme: true, smbios: $("smbios").value,
      usb_map_kind: $("usbmap").value, features, debug: false, sip: "enabled",
    };
  }

  function section(title, count, build) {
    const wrap = el("div", "section");
    const head = el("div", "section-head");
    head.append(el("h3", null, title), el("span", "count", count));
    wrap.appendChild(head);
    wrap.appendChild(build());
    return wrap;
  }

  function rowList(items) {
    const box = el("div", "rows");
    for (const item of items) {
      const row = el("div", "row");
      const name = el("div", "name", item.name);
      if (item.tag) {
        const t = el("span", "tag" + (item.tagWarn ? " tag-warn" : ""), item.tag);
        t.style.marginLeft = "7px";
        name.appendChild(t);
      }
      row.appendChild(name);
      row.appendChild(el("div", "val", item.value || ""));
      if (item.why) row.appendChild(el("div", "why", item.why));
      box.appendChild(row);
    }
    return box;
  }

  function commandFor(p, ctx) {
    const parts = ["efibuild build", `--platform ${p.platform}`, `--macos ${p.macos}`];
    if (p.chipset) parts.push(`--chipset ${p.chipset}`);
    if (p.motherboard_vendor) parts.push(`--vendor ${p.motherboard_vendor}`);
    if (p.cpu_cores > 0) parts.push(`--cores ${p.cpu_cores}`);
    if (p.igpu !== "none") parts.push("--igpu igpu", `--igpu-mode ${p.igpu_mode}`);
    if (p.dgpu !== "none") parts.push(`--dgpu ${p.dgpu}`);
    if (p.ethernet !== "auto") parts.push(`--ethernet ${p.ethernet}`);
    if (p.wifi !== "none") parts.push(`--wifi ${p.wifi}`);
    if (p.bluetooth !== "none") parts.push(`--bluetooth ${p.bluetooth}`);
    if (p.touchpad !== "none") parts.push(`--touchpad ${p.touchpad}`);
    if (p.audio_layout !== 1) parts.push(`--audio-layout ${p.audio_layout}`);
    if (p.smbios !== ctx.plat.smbios.default) parts.push(`--smbios ${p.smbios}`);
    if (p.usb_map_kind !== "none") parts.push(`--usb-map-kind ${p.usb_map_kind}`,
                                              "--usb-map <votre fichier>");
    for (const f of p.features) parts.push(`--feature ${f}`);
    parts.push("-o mon-efi");
    const lines = [];
    let line = parts[0];
    for (const part of parts.slice(1)) {
      if ((line + " " + part).length > 68) { lines.push(line + " \\"); line = "    " + part; }
      else line += " " + part;
    }
    lines.push(line);
    return lines.join("\n");
  }

  function render() {
    const profile = readProfile();
    const ctx = engine.resolve(profile);
    const ssdts = engine.ssdts(ctx);
    const { chosen, warnings: kextWarnings } = engine.kexts(ctx);
    const quirks = engine.quirks(ctx);
    const boot = engine.bootArgs(ctx);
    const blockers = engine.blockers(ctx);
    const notes = engine.warnings(ctx).concat(kextWarnings);
    const sm = engine.smbiosServes(ctx.smbios_model, ctx.macos);

    $("target").textContent = `${ctx.macos.name} · ${ctx.smbios_model}`;
    $("cores-field").style.display = ctx.family === "amd" ? "" : "none";

    const v = el("div", "verdict " + (blockers.length ? "v-bad" : notes.length ? "v-warn" : "v-ok"));
    v.appendChild(el("span", "verdict-chip",
      blockers.length ? "incompatible" : notes.length ? "faisable" : "sans réserve"));
    const vt = el("div");
    vt.appendChild(el("p", null, blockers.length
      ? blockers[0]
      : `${ctx.plat.name} sous ${ctx.macos.name}.`));
    vt.appendChild(el("p", "sub", sm.known && sm.ok === false
      ? `Le SMBIOS ${ctx.smbios_model} ne reçoit plus que macOS ${sm.served}.`
      : `${ssdts.length} SSDT, ${chosen.length} kexts, ${Object.keys(quirks).length} quirks à appliquer.`));
    v.appendChild(vt);
    $("verdict").replaceChildren(v);

    const manifest = el("div");

    manifest.appendChild(section("ACPI", `${ssdts.length}`, () => ssdts.length
      ? rowList(ssdts.map(s => ({ name: s.file, why: s.reason })))
      : el("div", "empty", "Aucun SSDT pour cette plateforme.")));

    manifest.appendChild(section("Kexts", `${chosen.length}`, () => rowList(
      chosen.map(k => ({
        name: k.bundles[0],
        tag: k.manual ? "à fournir" : null, tagWarn: true,
        value: k.repo ? k.repo.split("/")[0] : "",
        why: k.reason,
      })))));

    manifest.appendChild(section("Quirks", `${Object.keys(quirks).length}`, () => rowList(
      Object.entries(quirks).map(([k, val]) => ({
        name: k, value: val === true ? "vrai" : val === false ? "faux" : String(val),
      })))));

    manifest.appendChild(section("boot-args", `${boot.length}`, () => boot.length
      ? rowList([{ name: boot.join(" ") }])
      : el("div", "empty", "Aucun boot-arg nécessaire.")));

    if (notes.length || blockers.length) {
      manifest.appendChild(section("À savoir", `${blockers.length + notes.length}`, () => {
        const box = el("div", "rows");
        for (const b of blockers) {
          const n = el("div", "note n-bad");
          n.append(el("span", "mark", "×"), el("span", null, b));
          box.appendChild(n);
        }
        for (const w of notes) {
          const n = el("div", "note n-warn");
          n.append(el("span", "mark", "!"), el("span", null, w));
          box.appendChild(n);
        }
        return box;
      }));
    }

    $("manifest").replaceChildren(manifest);
    $("command").textContent = commandFor(profile, ctx);
    $("copied").hidden = true;
  }

  $("smbios").addEventListener("change", () => { smbiosTouched = true; });
  $("family").addEventListener("change", () => { syncPlatforms(); render(); });
  $("platform").addEventListener("change", () => { syncSmbios(); render(); });
  for (const id of ["macos", "chipset", "vendor", "cores", "alcid", "igpu", "dgpu",
                    "smbios", "ethernet", "wifi", "bluetooth", "touchpad", "usbmap"]) {
    $(id).addEventListener("input", render);
  }

  $("copy").addEventListener("click", async () => {
    const text = $("command").textContent;
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const range = document.createRange();
      range.selectNodeContents($("command"));
      const sel = getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
    }
    $("copied").hidden = false;
  });

  $("theme").addEventListener("click", () => {
    const root = document.documentElement;
    const dark = root.getAttribute("data-theme") === "dark" ||
      (!root.getAttribute("data-theme") &&
       matchMedia("(prefers-color-scheme: dark)").matches);
    root.setAttribute("data-theme", dark ? "light" : "dark");
  });

  syncPlatforms("coffee-lake-desktop");
  $("platform").value = "coffee-lake-desktop";
  syncSmbios();
  $("igpu").value = "headless";
  render();
})();
