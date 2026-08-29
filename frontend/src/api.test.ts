import { afterEach, describe, expect, it, vi } from "vitest";

import { importProducts } from "./api";

describe("product import API", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("posts the CSV and images only to the canonical product import endpoint", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          imported_products: 0,
          imported_variants: 0,
          imported_images: 0,
          products: [],
        }),
        { status: 201, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const csv = new File(["valid-csv"], "products.csv", { type: "text/csv" });
    const front = new File(["front"], "front.jpg", { type: "image/jpeg" });
    const back = new File(["back"], "back.jpg", { type: "image/jpeg" });

    await importProducts("access-token", csv, [front, back]);

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, request] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/products/import");
    expect(request).toEqual(
      expect.objectContaining({
        method: "POST",
        headers: { Authorization: "Bearer access-token" },
      }),
    );
    const body = request?.body;
    expect(body).toBeInstanceOf(FormData);
    expect((body as FormData).get("file")).toBe(csv);
    expect((body as FormData).getAll("images")).toEqual([front, back]);
  });
});
