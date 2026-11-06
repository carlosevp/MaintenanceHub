import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import axe from "axe-core";
import { LoginPage } from "@/routes/LoginPage";
import { ExperienceProvider } from "@/features/experience/ExperienceContext";

vi.mock("@/features/auth/AuthContext", () => ({
  useAuth: () => ({
    user: null,
    loading: false,
    login: vi.fn(),
    logout: vi.fn(),
  }),
}));

describe("LoginPage a11y", () => {
  it("has no serious or critical axe violations", async () => {
    const { container } = render(
      <MemoryRouter>
        <ExperienceProvider>
          <LoginPage />
        </ExperienceProvider>
      </MemoryRouter>,
    );
    const results = await axe.run(container, {
      runOnly: {
        type: "tag",
        values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"],
      },
    });
    const material = results.violations.filter((v) =>
      ["serious", "critical"].includes(v.impact || ""),
    );
    expect(material, JSON.stringify(material, null, 2)).toEqual([]);
  });
});
