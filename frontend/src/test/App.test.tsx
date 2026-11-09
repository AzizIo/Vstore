import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { App } from "../App";

describe("VILTARA SHOP landing screen", () => {
  it("renders the marketplace brand and network", () => {
    render(<App />);

    expect(screen.getByText("VILTARA")).toBeInTheDocument();
    expect(screen.getByText("TON MARKET")).toBeInTheDocument();
    expect(screen.getByText("VILTARA SHOP")).toBeInTheDocument();
  });

  it("introduces the digital collectibles marketplace", () => {
    render(<App />);

    expect(
      screen.getByText("DIGITAL COLLECTIBLES MARKETPLACE"),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "Discover rare digital gifts.",
    );
    expect(
      screen.getByText(
        "A curated marketplace for verifiable Telegram collectibles and TON NFTs.",
      ),
    ).toBeInTheDocument();
  });

  it("shows the preview state and safe-transfer notice", () => {
    render(<App />);

    expect(screen.getByText("Marketplace preview")).toBeInTheDocument();
    expect(
      screen.getByText("Coming together, one verified asset at a time."),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "The marketplace interface is being prepared. Asset verification and safe transfers come first.",
      ),
    ).toBeInTheDocument();
  });

  it("exposes the collection exploration control", () => {
    render(<App />);

    expect(
      screen.getByRole("button", { name: "Explore collection" }),
    ).toBeInTheDocument();
  });
});
