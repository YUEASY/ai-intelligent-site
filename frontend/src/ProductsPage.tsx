import {
  Alert,
  Button,
  Card,
  Drawer,
  Empty,
  Image,
  Popconfirm,
  Space,
  Spin,
  Tag,
  Typography,
} from "antd";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  ApiError,
  type Product,
  type ProductSnapshot,
  generateProductDraft,
  getProductVersions,
  getProducts,
  importProducts,
  rollbackProduct,
} from "./api";
import { withAuthenticatedSession } from "./auth";
import "./ProductsPage.css";

const { Text, Title } = Typography;

export default function ProductsPage({
  onSessionExpired,
}: {
  onSessionExpired?: () => void;
}) {
  const [products, setProducts] = useState<Product[]>();
  const [selected, setSelected] = useState<Product>();
  const [loadError, setLoadError] = useState(false);
  const [csvFile, setCsvFile] = useState<File>();
  const [imageFiles, setImageFiles] = useState<File[]>([]);
  const [importing, setImporting] = useState(false);
  const [importNotice, setImportNotice] = useState<string>();
  const [importErrors, setImportErrors] = useState<string[]>([]);
  const [generatingId, setGeneratingId] = useState<string>();
  const [generateNotice, setGenerateNotice] = useState<string>();
  const [generateError, setGenerateError] = useState<string>();
  const [versions, setVersions] = useState<ProductSnapshot[]>();
  const [rollbackNotice, setRollbackNotice] = useState<string>();
  const csvInput = useRef<HTMLInputElement>(null);
  const imageInput = useRef<HTMLInputElement>(null);

  const loadProducts = useCallback(async () => {
    try {
      const loadedProducts = await withAuthenticatedSession((token) =>
        getProducts(token),
      );
      setProducts(loadedProducts);
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) {
        onSessionExpired?.();
      }
      setLoadError(true);
    }
  }, [onSessionExpired]);

  useEffect(() => {
    void Promise.resolve().then(loadProducts);
  }, [loadProducts]);

  const generateFor = async (product: Product) => {
    setGeneratingId(product.id);
    setGenerateNotice(undefined);
    setGenerateError(undefined);
    try {
      await withAuthenticatedSession((token) =>
        generateProductDraft(token, product.id),
      );
      setGenerateNotice(`已为 ${product.title} 触发生成任务，草稿生成后进入审核队列`);
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) {
        onSessionExpired?.();
      }
      setGenerateError(
        cause instanceof ApiError ? cause.message : "生成失败，请稍后重试",
      );
    } finally {
      setGeneratingId(undefined);
    }
  };

  useEffect(() => {
    const productId = selected?.id;
    if (!productId) return;
    let cancelled = false;
    void withAuthenticatedSession((token) =>
      getProductVersions(token, productId),
    )
      .then((loaded) => {
        if (!cancelled) setVersions(loaded);
      })
      .catch(() => {
        if (!cancelled) setVersions([]);
      });
    return () => {
      cancelled = true;
    };
  }, [selected?.id]);

  const rollbackToVersion = async (version: number) => {
    if (!selected) return;
    setRollbackNotice(undefined);
    try {
      await withAuthenticatedSession((token) =>
        rollbackProduct(token, selected.id, version),
      );
      setRollbackNotice(`已回滚到版本 ${version}`);
      await loadProducts();
      const reloaded = await withAuthenticatedSession((token) =>
        getProductVersions(token, selected.id),
      );
      setVersions(reloaded);
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) {
        onSessionExpired?.();
      }
      setRollbackNotice(
        cause instanceof ApiError ? cause.message : "回滚失败，请稍后重试",
      );
    }
  };

  const submitImport = async () => {
    if (!csvFile) return;
    setImporting(true);
    setImportNotice(undefined);
    setImportErrors([]);
    try {
      const result = await withAuthenticatedSession((token) =>
        importProducts(token, csvFile, imageFiles),
      );
      setProducts((current) => {
        const importedIds = new Set(result.products.map((product) => product.id));
        return [
          ...(current ?? []).filter((product) => !importedIds.has(product.id)),
          ...result.products,
        ];
      });
      setImportNotice(
        `已导入 ${result.imported_products} 个商品、${result.imported_variants} 个变体、${result.imported_images} 张图片`,
      );
      setCsvFile(undefined);
      setImageFiles([]);
      if (csvInput.current) csvInput.current.value = "";
      if (imageInput.current) imageInput.current.value = "";
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) {
        onSessionExpired?.();
      }
      setImportErrors(
        cause instanceof ApiError && cause.validationIssues.length
          ? cause.validationIssues.map(
              (issue) => `第 ${issue.line} 行：${issue.message}`,
            )
          : [cause instanceof ApiError ? cause.message : "上传失败，请稍后重试"],
      );
    } finally {
      setImporting(false);
    }
  };

  return (
    <section className="products-page">
      <Space orientation="vertical" size={8}>
        <Text className="page-eyebrow">CANONICAL PRODUCTS</Text>
        <Title>商品列表</Title>
        <Text type="secondary">查看当前商户已导入的商品标准模型与变体。</Text>
      </Space>

      <Card className="product-import-card" variant="borderless">
        <Space orientation="vertical" size="middle">
          <Title level={3}>导入商品</Title>
          <Text type="secondary">
            上传 UTF-8 CSV；CSV 中的本地图片文件名需与图片包一致。
          </Text>
          <Space wrap className="import-examples">
            <a
              href="/examples/product-import-example.csv"
              download="product-import-example.csv"
            >
              下载 CSV 示例
            </a>
            <a
              href="/examples/product-example.svg"
              download="product-example.svg"
            >
              下载配套图片
            </a>
            <Text type="secondary">下载后可直接选择两个示例文件试传。</Text>
          </Space>
          <label className="file-field">
            <Text strong>CSV 文件</Text>
            <input
              aria-label="CSV 文件"
              ref={csvInput}
              type="file"
              accept=".csv,text/csv"
              onChange={(event) => setCsvFile(event.target.files?.[0])}
            />
            <Text type="secondary">{csvFile?.name ?? "尚未选择"}</Text>
          </label>
          <label className="file-field">
            <Text strong>商品图片</Text>
            <input
              aria-label="商品图片"
              ref={imageInput}
              type="file"
              accept="image/*"
              multiple
              onChange={(event) => setImageFiles(Array.from(event.target.files ?? []))}
            />
            <Text type="secondary">
              {imageFiles.length ? `${imageFiles.length} 张图片` : "可选"}
            </Text>
          </label>
          <Button
            type="primary"
            disabled={!csvFile}
            loading={importing}
            onClick={() => void submitImport()}
          >
            上传并导入
          </Button>
        </Space>
      </Card>

      {importNotice && <Alert showIcon type="success" message={importNotice} />}
      {generateNotice && <Alert showIcon type="success" message={generateNotice} />}
      {generateError && (
        <Alert
          showIcon
          type="error"
          title="生成失败"
          description={generateError}
        />
      )}
      {importErrors.length > 0 && (
        <Alert
          showIcon
          type="error"
          title="导入失败"
          action={
            <Button
              disabled={!csvFile}
              loading={importing}
              onClick={() => void submitImport()}
            >
              重试上传
            </Button>
          }
          description={
            <ul className="import-errors">
              {importErrors.map((error) => <li key={error}>{error}</li>)}
            </ul>
          }
        />
      )}

      {loadError && (
        <Alert
          showIcon
          type="error"
          message="暂时无法加载商品列表"
          action={
            <Button
              onClick={() => {
                setLoadError(false);
                void loadProducts();
              }}
            >
              重试
            </Button>
          }
        />
      )}

      {products === undefined && !loadError ? (
        <div className="products-loading"><Spin /></div>
      ) : products?.length === 0 ? (
        <Card className="products-empty"><Empty description="尚未导入商品" /></Card>
      ) : (
        <div className="product-grid">
          {products?.map((product) => (
            <Card key={product.id} className="product-card" variant="borderless">
              <Space orientation="vertical" size={10}>
                <Space wrap>
                  <Tag color="green">{product.status}</Tag>
                  <Text type="secondary">{product.category}</Text>
                </Space>
                <Title level={3}>{product.title}</Title>
                <Text>{product.sku}</Text>
                <Text type="secondary">{product.variants.length} 个变体</Text>
                <Space wrap>
                  <Button
                    onClick={() => {
                      setSelected(product);
                      setVersions(undefined);
                      setRollbackNotice(undefined);
                    }}
                  >
                    查看详情
                  </Button>
                  <Button
                    type="primary"
                    loading={generatingId === product.id}
                    onClick={() => void generateFor(product)}
                  >
                    生成 AI 草稿
                  </Button>
                </Space>
              </Space>
            </Card>
          ))}
        </div>
      )}

      <Drawer
        title={selected?.title}
        open={selected !== undefined}
        size="large"
        onClose={() => {
          setSelected(undefined);
          setVersions(undefined);
          setRollbackNotice(undefined);
        }}
      >
        {selected && (
          <Space orientation="vertical" size="large" className="product-detail">
            <div>
              <Text type="secondary">商品描述</Text>
              <p>{selected.description || "暂无描述"}</p>
            </div>
            <div>
              <Text type="secondary">图片</Text>
              <Image.PreviewGroup>
                <div className="product-image-gallery">
                  {selected.images
                    .filter((image) => /^https?:\/\//.test(image))
                    .map((image) => (
                      <Image
                        key={image}
                        src={image}
                        alt={`${selected.title} 商品图`}
                        width={180}
                      />
                    ))}
                </div>
              </Image.PreviewGroup>
              <div className="product-image-references">
                {selected.images.map((image) => <Tag key={image}>{image}</Tag>)}
              </div>
            </div>
            <div>
              <Title level={4}>变体</Title>
              <div className="variant-list">
                {selected.variants.map((variant) => (
                  <article key={variant.id} className="variant-card">
                    <Text strong>{variant.sku}</Text>
                    <Text>
                      {Object.entries(variant.options)
                        .map(([name, value]) => `${name}: ${value}`)
                        .join(" / ") || "默认变体"}
                    </Text>
                    <Space wrap>
                      <Text>价格 {variant.price}</Text>
                      <Text>成本 {variant.cost ?? "—"}</Text>
                      <Text>库存 {variant.inventory}</Text>
                    </Space>
                  </article>
                ))}
              </div>
            </div>
            <div>
              <Title level={4}>版本历史</Title>
              {rollbackNotice && (
                <Alert showIcon type="success" message={rollbackNotice} />
              )}
              {versions === undefined ? (
                <Spin />
              ) : versions.length === 0 ? (
                <Text type="secondary">暂无版本快照</Text>
              ) : (
                <div className="version-list">
                  {versions.map((snapshot) => (
                    <article key={snapshot.id} className="version-card">
                      <Space direction="vertical" size={4}>
                        <Space wrap>
                          <Text strong>版本 {snapshot.version}</Text>
                          <Tag>{snapshot.kind === "publish" ? "发布" : "回滚"}</Tag>
                          <Text type="secondary">
                            {new Date(snapshot.created_at).toLocaleString()}
                          </Text>
                        </Space>
                        <Text type="secondary">操作者 {snapshot.actor}</Text>
                        {snapshot.restored_version !== null && (
                          <Text type="secondary">
                            恢复自版本 {snapshot.restored_version}
                          </Text>
                        )}
                        <Popconfirm
                          title={`回滚到版本 ${snapshot.version}？`}
                          description="将整体恢复商品到该版本快照，并写入商户店铺。"
                          okText="确认回滚"
                          cancelText="取消"
                          onConfirm={() => rollbackToVersion(snapshot.version)}
                        >
                          <Button size="small">回滚到此版本</Button>
                        </Popconfirm>
                      </Space>
                    </article>
                  ))}
                </div>
              )}
            </div>
          </Space>
        )}
      </Drawer>
    </section>
  );
}
