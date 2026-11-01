import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/** Wording rule: the UI must never suggest a prediction or a look-ahead. Scans every non-test source file. */
const BANNED: [string, RegExp][] = [
  ["forecast", /forecast/i],
  ["predicted flood", /predicted\s+flood/i],
  ["next day(s)", /next[\s-]+(\d+[\s-]+|n\s+)?days?\b/i],
  ["daily flood prediction", /daily\s+(flood\s+)?(risk|probabilit|prediction)/i],
  ["tomorrow", /tomorrow/i],
];

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((f) => {
    const p = join(dir, f);
    if (statSync(p).isDirectory()) return f === "test" ? [] : files(p);
    return /\.(ts|tsx|css)$/.test(f) ? [p] : [];
  });
}

describe("wording rules", () => {
  const srcDir = join(__dirname, "..");
  for (const [name, re] of BANNED) {
    it(`never uses "${name}" in UI source`, () => {
      const hits = files(srcDir).filter((f) => re.test(readFileSync(f, "utf8")));
      expect(hits).toEqual([]);
    });
  }
  it("scans a meaningful number of files", () => {
    expect(files(srcDir).length).toBeGreaterThan(20);
  });
});
