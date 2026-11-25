import { describe, expect, it } from "vitest";
import { cardTitle, relativeDay, shortReference } from "../src/components/cardText";

const fallback = (area: string, category: string) => `${category} near ${area}`;

describe("complaint card wording", () => {
  it("keeps the citizen's own words", () => {
    expect(cardTitle("Deep crater in front of the school gate", "pothole", "Pothole", "HSR Layout", fallback)).toBe(
      "Deep crater in front of the school gate",
    );
  });

  it("does not repeat the category as a title", () => {
    expect(cardTitle("pothole", "pothole", "Pothole", "HSR Layout", fallback)).toBe("Pothole near HSR Layout");
    expect(cardTitle("Pothole!", "pothole", "Pothole", null, fallback)).toBe("Pothole");
    expect(cardTitle("ok", "pothole", "Pothole", "Koramangala", fallback)).toBe("Pothole near Koramangala");
    expect(cardTitle(null, "garbage_accumulation", "Garbage", "BTM", fallback)).toBe("Garbage near BTM");
  });

  it("shortens long references only", () => {
    expect(shortReference("NS-99D08CD3680C47879D73E645A72C8471")).toBe("NS-99D08CD3");
    expect(shortReference("NS-1234")).toBe("NS-1234");
    expect(shortReference(null)).toBe("");
  });

  it("describes dates relative to today, with a plain date for old ones", () => {
    const now = new Date(2026, 10, 25, 15, 0);
    expect(relativeDay(new Date(2026, 10, 25, 1, 0).toISOString(), "en", now)).toBe("today");
    expect(relativeDay(new Date(2026, 10, 24, 23, 0).toISOString(), "en", now)).toBe("yesterday");
    expect(relativeDay(new Date(2026, 10, 22, 9, 0).toISOString(), "en", now)).toBe("3 days ago");
    expect(relativeDay(new Date(2026, 8, 1).toISOString(), "en", now)).toBe(new Date(2026, 8, 1).toLocaleDateString("en"));
  });
});
