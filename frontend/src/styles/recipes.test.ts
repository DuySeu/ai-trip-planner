import { globSync, readFileSync } from "node:fs";
import { expect, it } from "vitest";

it("app_has_no_stylesheet_of_its_own", () => {
  expect(globSync("src/**/*.css")).toEqual([]);
});

it("components_use_tokens_not_literal_colours", () => {
  const offenders = globSync("src/**/*.tsx").filter((file) => /#[0-9a-f]{3,8}\b|rgba?\(/i.test(readFileSync(file, "utf8")));
  expect(offenders).toEqual([]);
});
