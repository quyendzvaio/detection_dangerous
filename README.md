# Industrial Safety AI Pipeline

Nhánh tích hợp sản phẩm hiện có đường chạy từ camera/video đến PostgreSQL:

```text
Layer 0 → Layer 1 → Layer 2 → EventBus → FastAPI Layer 4 → PostgreSQL
```

Tài liệu chuẩn được tách theo phạm vi:

- [docs/PRODUCT_PIPELINE.md](docs/PRODUCT_PIPELINE.md): pipeline và event contract Layer 0–4.
- [docs/TEAM_ONBOARDING_LAYER5_6.md](docs/TEAM_ONBOARDING_LAYER5_6.md): trạng thái, cấu trúc, API và kế hoạch bàn giao Backend/UI Layer 5–6.

Smoke test một camera USB. PostgreSQL, Adminer, backend và Triton chạy local; chỉ evidence JPEG/MP4 được upload trực tiếp lên Azure Blob Cloud. Trước khi chạy, sao chép `.env.example` thành `.env` và điền `AZURE_STORAGE_CONNECTION_STRING`:

```bash
./run_pipeline_demo.sh --camera 1:cam1:0 --show
```

Sau khi chạy:

- API docs: <http://localhost:8080/docs>
- Adminer: <http://localhost:8081>
- Health: <http://localhost:8080/health/ready>

Không dùng README hoặc tài liệu từ các nhánh feature cũ làm contract tích hợp. Mọi thay đổi contract phải cập nhật code, migration, test serialization/ingestion và `docs/PRODUCT_PIPELINE.md` trong cùng pull request.
