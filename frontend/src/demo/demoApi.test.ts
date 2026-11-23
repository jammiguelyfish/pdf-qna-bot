// @vitest-environment node
// (the backend uses Web Crypto and Blob, which Node provides natively)
import { describe, expect, it } from "vitest";
import { demoApi, demoQuestions } from "./demoApi";

const pdf = (body: string, name: string) => new File([`%PDF-1.4\n${body}`], name, { type: "application/pdf" });

describe("demo backend", () => {
  it("starts with the three sample documents, ready and searchable", async () => {
    const docs = await demoApi.documents();
    expect(docs.map((d) => d.status)).toEqual(["ready", "ready", "ready"]);
  });

  it("replays the recorded answer to a suggested question, with sources", async () => {
    const r = await demoApi.ask(demoQuestions[0]);
    expect(r.messages[1].content.length).toBeGreaterThan(0);
    expect(r.messages[1].sources.length).toBeGreaterThan(0);
  });

  it("falls back to passages for other questions", async () => {
    const r = await demoApi.ask("Where is the Great Buddha?");
    expect(r.messages[1].content).toMatch(/no language model/);
    expect(r.messages[1].sources.some((s) => s.document === "tokyo-itinerary.pdf")).toBe(true);
  });

  it("rejects non-PDFs and flags a same-name different-content upload", async () => {
    await expect(demoApi.upload(new File(["hi"], "a.txt"))).rejects.toMatchObject({ code: "not_pdf" });
    await expect(demoApi.upload(new File(["hello"], "b.pdf"))).rejects.toMatchObject({ code: "not_pdf" });
    const first = pdf("one", "notes.pdf");
    await demoApi.upload(first);
    await expect(demoApi.upload(pdf("one", "other-name.pdf"))).rejects.toMatchObject({
      status: 409,
      code: "duplicate_content",
    });
    await expect(demoApi.upload(pdf("two", "notes.pdf"))).rejects.toMatchObject({ code: "name_exists" });
    await demoApi.upload(pdf("two", "notes.pdf"), true);
    expect((await demoApi.documents()).filter((d) => d.name === "notes.pdf")).toHaveLength(1);
  });

  it("stops replaying a recorded answer once its source file is replaced", async () => {
    await demoApi.upload(pdf("different content", "south-korea-itinerary.pdf"), true);
    const r = await demoApi.ask(demoQuestions[0]);
    expect(r.messages[1].content).toMatch(/no language model/);
  });
});
