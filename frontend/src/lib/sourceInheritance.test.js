import { inheritSourceHeader } from "./sourceInheritance";

const header = (over = {}) => ({ source_header: { default_unit_id: "", ...over } });

describe("inheritSourceHeader", () => {
  it("mewarisi nilai bila SEMUA sumber mengisi nilai yang sama", () => {
    const next = inheritSourceHeader({ default_unit_id: "" }, [
      header({ default_unit_id: "UNIT-A" }),
      header({ default_unit_id: "UNIT-A" }),
    ]);
    expect(next.default_unit_id).toBe("UNIT-A");
  });

  it("TIDAK mengisi header bila hanya sebagian sumber punya nilai (kasus Tarik MRO campuran)", () => {
    const next = inheritSourceHeader({ default_unit_id: "" }, [
      header({ default_unit_id: "" }),
      header({ default_unit_id: "SN4324" }),
    ]);
    expect(next.default_unit_id).toBe("");
  });

  it("membiarkan nilai form apa adanya bila tidak ada sumber yang mengisi", () => {
    const next = inheritSourceHeader({ default_unit_id: "ISI-SENDIRI" }, [header(), header()]);
    expect(next.default_unit_id).toBe("ISI-SENDIRI");
  });

  it("mengosongkan header bila sumber saling berbeda", () => {
    const next = inheritSourceHeader({ default_unit_id: "LAMA" }, [
      header({ default_unit_id: "UNIT-A" }),
      header({ default_unit_id: "UNIT-B" }),
    ]);
    expect(next.default_unit_id).toBe("");
  });

  it("tetap mewarisi boolean tax_inclusive=false saat semua sumber sama", () => {
    const next = inheritSourceHeader({ tax_inclusive: true }, [
      header({ tax_inclusive: false }),
      header({ tax_inclusive: false }),
    ]);
    expect(next.tax_inclusive).toBe(false);
  });
});
