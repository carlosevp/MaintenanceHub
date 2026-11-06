import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AdminShell } from "./AdminShell";

const useAuth = vi.fn();

vi.mock("@/features/auth/AuthContext", () => ({
  useAuth: () => useAuth(),
}));

afterEach(() => {
  cleanup();
});

describe("AdminShell authz gate", () => {
  it("blocks non-administrators", () => {
    useAuth.mockReturnValue({
      user: { id: "1", email: "p@x", display_name: "Pub", roles: ["publisher"] },
      loading: false,
    });
    render(
      <MemoryRouter initialEntries={["/admin"]}>
        <Routes>
          <Route path="/admin" element={<AdminShell />} />
          <Route path="/" element={<div>home</div>} />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByText(/requires the/i)).toBeInTheDocument();
    expect(screen.getByText(/platform_administrator/i)).toBeInTheDocument();
  });

  it("renders outlet for administrators", () => {
    useAuth.mockReturnValue({
      user: {
        id: "2",
        email: "a@x",
        display_name: "Admin",
        roles: ["platform_administrator"],
      },
      loading: false,
    });
    render(
      <MemoryRouter initialEntries={["/admin"]}>
        <Routes>
          <Route path="/admin" element={<AdminShell />}>
            <Route index element={<div>Admin overview content</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByText("Admin overview content")).toBeInTheDocument();
    expect(screen.getByText(/Secrets stay in environment/i)).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Administration" })).toBeInTheDocument();
  });
});
