import fs from "node:fs";
const target = new URL("../dist/", import.meta.url);
const root = new URL("../node_modules/", import.meta.url);
const pin = JSON.parse(
  fs.readFileSync(new URL("../upstream.json", import.meta.url), "utf8"),
);
const notices = [
  `MoneyPrinter OpenCut integration\n${pin.edition}: ${pin.license}, ${pin.revision}\n`,
];
for (const folder of fs.readdirSync(root, { withFileTypes: true })) {
  if (!folder.isDirectory() || folder.name.startsWith(".")) continue;
  const paths = folder.name.startsWith("@")
    ? fs
        .readdirSync(new URL(folder.name + "/", root))
        .map((p) => folder.name + "/" + p)
    : [folder.name];
  for (const item of paths) {
    const base = new URL(item + "/", root);
    if (!fs.existsSync(new URL("package.json", base))) continue;
    const info = JSON.parse(
      fs.readFileSync(new URL("package.json", base), "utf8"),
    );
    const files = fs
      .readdirSync(base)
      .filter((n) => /^(license|licence|copying|notice)(\.|$)/i.test(n));
    notices.push(
      `\n--- ${info.name}@${info.version} (${typeof info.license === "string" ? info.license : "see license"}) ---\n`,
    );
    for (const file of files) {
      const value = new URL(file, base);
      if (fs.statSync(value).isFile())
        notices.push(fs.readFileSync(value, "utf8"));
    }
  }
}
fs.writeFileSync(
  new URL("THIRD_PARTY_NOTICES.txt", target),
  notices.join("\n"),
);
fs.copyFileSync(
  new URL("../OPENCUT_LICENSE", import.meta.url),
  new URL("OPENCUT_LICENSE", target),
);
fs.writeFileSync(
  new URL("moneyprinter-build.json", target),
  JSON.stringify(pin) + "\n",
);
