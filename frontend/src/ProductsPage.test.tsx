import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, getProducts, importProducts } from "./api";
import ProductsPage from "./ProductsPage";

vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  getProducts: vi.fn(),
  importProducts: vi.fn(),
}));

vi.mock("./auth", () => ({
  withAuthenticatedSession: <T,>(operation: (token: string) => Promise<T>) =>
    operation("saved-access-token"),
}));

const mockedGetProducts = vi.mocked(getProducts);
const mockedImportProducts = vi.mocked(importProducts);

describe("ProductsPage", () => {
  beforeEach(() => {
    mockedGetProducts.mockReset();
    mockedImportProducts.mockReset();
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("lists imported products and shows every variant in the detail view", async () => {
    mockedGetProducts.mockResolvedValue([
      {
        id: "product-id",
        tenant_id: "tenant-id",
        source: "merchant_csv",
        source_id: "product-1",
        sku: "TSHIRT",
        title: "Classic T-Shirt",
        description: "Heavy cotton tee",
        category: "Apparel",
        tags: ["summer", "cotton"],
        images: ["front.jpg", "back.jpg"],
        meta_title: "Classic Cotton T-Shirt",
        meta_description: "Shop our classic cotton T-shirt",
        handle: "classic-t-shirt",
        status: "draft",
        variants: [
          {
            id: "variant-black",
            sku: "TSHIRT-BLK-S",
            options: { Color: "Black", Size: "S" },
            price: "29.90",
            cost: "12.50",
            inventory: 8,
            image: "black-small.jpg",
          },
          {
            id: "variant-white",
            sku: "TSHIRT-WHT-M",
            options: { Color: "White", Size: "M" },
            price: "31.90",
            cost: null,
            inventory: 5,
            image: null,
          },
        ],
      },
    ]);
    const user = userEvent.setup();

    render(<ProductsPage />);

    expect(
      await screen.findByRole("heading", { name: "商品列表" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Classic T-Shirt")).toBeInTheDocument();
    expect(screen.getByText("2 个变体")).toBeInTheDocument();
    expect(mockedGetProducts).toHaveBeenCalledWith("saved-access-token");

    await user.click(screen.getByRole("button", { name: "查看详情" }));

    expect(screen.getByRole("dialog", { name: "Classic T-Shirt" })).toBeVisible();
    expect(screen.getByText("Heavy cotton tee")).toBeInTheDocument();
    expect(screen.getByText("front.jpg")).toBeInTheDocument();
    expect(screen.getByText("TSHIRT-BLK-S")).toBeInTheDocument();
    expect(screen.getByText("Color: Black / Size: S")).toBeInTheDocument();
    expect(screen.getByText("价格 29.90")).toBeInTheDocument();
    expect(screen.getByText("成本 12.50")).toBeInTheDocument();
    expect(screen.getByText("库存 8")).toBeInTheDocument();
    expect(screen.getByText("TSHIRT-WHT-M")).toBeInTheDocument();
  });

  it("uploads a valid CSV with its images and shows the imported product", async () => {
    const importedProduct = {
      id: "product-id",
      tenant_id: "tenant-id",
      source: "merchant_csv",
      source_id: "product-1",
      sku: "MUG",
      title: "Ceramic Mug",
      description: "A sturdy mug",
      category: "Home",
      tags: ["gift"],
      images: ["mug.jpg"],
      meta_title: "Ceramic Mug",
      meta_description: "A sturdy ceramic mug",
      handle: "ceramic-mug",
      status: "draft" as const,
      variants: [
        {
          id: "variant-id",
          sku: "MUG-WHITE",
          options: { Color: "White" },
          price: "19.90",
          cost: "7.50",
          inventory: 12,
          image: "mug.jpg",
        },
      ],
    };
    mockedGetProducts.mockResolvedValue([
      {
        ...importedProduct,
        id: "existing-product",
        source_id: "existing-product",
        sku: "EXISTING",
        title: "Existing Product",
        handle: "existing-product",
      },
    ]);
    mockedImportProducts.mockResolvedValue({
      imported_products: 1,
      imported_variants: 1,
      imported_images: 1,
      products: [importedProduct],
    });
    const user = userEvent.setup();
    render(<ProductsPage />);
    await screen.findByText("Existing Product");
    const csv = new File(
      [
        "source,source_id,sku,title,description,category,tags,images,meta_title,meta_description,handle,status,variant_sku,option1_name,option1_value,option2_name,option2_value,price,cost,inventory,variant_image\n",
        "merchant_csv,product-1,MUG,Ceramic Mug,A sturdy mug,Home,gift,mug.jpg,Ceramic Mug,A sturdy ceramic mug,ceramic-mug,draft,MUG-WHITE,Color,White,,,19.90,7.50,12,mug.jpg\n",
      ],
      "products.csv",
      { type: "text/csv" },
    );
    const image = new File(["image-bytes"], "mug.jpg", { type: "image/jpeg" });

    await user.upload(screen.getByLabelText("CSV 文件"), csv);
    await user.upload(screen.getByLabelText("商品图片"), image);
    await user.click(screen.getByRole("button", { name: "上传并导入" }));

    expect(mockedImportProducts).toHaveBeenCalledWith(
      "saved-access-token",
      csv,
      [image],
    );
    expect(
      await screen.findByText("已导入 1 个商品、1 个变体、1 张图片"),
    ).toBeInTheDocument();
    expect(screen.getByText("Ceramic Mug")).toBeInTheDocument();
    expect(screen.getByText("Existing Product")).toBeInTheDocument();
    expect(screen.getByLabelText<HTMLInputElement>("CSV 文件").value).toBe("");
    expect(screen.getByLabelText<HTMLInputElement>("商品图片").value).toBe("");
  });

  it("shows exact invalid row numbers without reporting partial success", async () => {
    mockedGetProducts.mockResolvedValue([]);
    mockedImportProducts.mockRejectedValue(
      new ApiError("CSV 校验失败", 422, [
        { line: 7, message: "title: Field required" },
        { line: 12, message: "price: Input should be a valid decimal" },
      ]),
    );
    const user = userEvent.setup();
    render(<ProductsPage />);
    await screen.findByText("尚未导入商品");
    const csv = new File(["invalid"], "invalid.csv", { type: "text/csv" });

    await user.upload(screen.getByLabelText("CSV 文件"), csv);
    await user.click(screen.getByRole("button", { name: "上传并导入" }));

    expect(
      await screen.findByText("第 7 行：title: Field required"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("第 12 行：price: Input should be a valid decimal"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/^已导入/)).not.toBeInTheDocument();
    expect(screen.getByText("尚未导入商品")).toBeInTheDocument();
  });

  it("retries a failed upload with the same selected files", async () => {
    mockedGetProducts.mockResolvedValue([]);
    mockedImportProducts
      .mockRejectedValueOnce(new ApiError("网络中断", 503))
      .mockResolvedValueOnce({
        imported_products: 1,
        imported_variants: 1,
        imported_images: 0,
        products: [
          {
            id: "retried-product",
            tenant_id: "tenant-id",
            source: "merchant_csv",
            source_id: "retry-1",
            sku: "RETRY",
            title: "Retry Product",
            description: "",
            category: "Test",
            tags: [],
            images: [],
            meta_title: "",
            meta_description: "",
            handle: "retry-product",
            status: "draft",
            variants: [],
          },
        ],
      });
    const user = userEvent.setup();
    render(<ProductsPage />);
    await screen.findByText("尚未导入商品");
    const csv = new File(["valid"], "retry.csv", { type: "text/csv" });

    await user.upload(screen.getByLabelText("CSV 文件"), csv);
    await user.click(screen.getByRole("button", { name: "上传并导入" }));

    expect(await screen.findByText("网络中断")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "重试上传" }));

    expect(mockedImportProducts).toHaveBeenNthCalledWith(
      2,
      "saved-access-token",
      csv,
      [],
    );
    expect(await screen.findByText("Retry Product")).toBeInTheDocument();
  });

  it("notifies the shell when the product session has expired", async () => {
    mockedGetProducts.mockRejectedValue(new ApiError("会话已过期", 401));
    const onSessionExpired = vi.fn();

    render(<ProductsPage onSessionExpired={onSessionExpired} />);

    expect(await screen.findByText("暂时无法加载商品列表")).toBeInTheDocument();
    expect(onSessionExpired).toHaveBeenCalledOnce();
  });
});
