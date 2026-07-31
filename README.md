# Industrial Safety AI Pipeline

Nhánh `develop` là đường tích hợp sản phẩm. Luồng hiện tại hỗ trợ nhiều camera độc lập từ Layer 0 đến Layer 2: OpenCV ingest, YOLO Pose trên Triton, BoT-SORT, restricted-zone, fall detection và PPE.

Tài liệu chuẩn duy nhất về kiến trúc, workflow, input/output, event schema, trạng thái đã làm/chưa làm và cách chạy nằm tại:

- [docs/PRODUCT_PIPELINE.md](docs/PRODUCT_PIPELINE.md)

Smoke test một camera USB:

```bash
./run_pipeline_demo.sh --camera 1:cam1:0 --show
```

Không dùng README hoặc tài liệu từ các nhánh feature cũ làm contract tích hợp. Mọi thay đổi contract phải cập nhật code, test serialization và `docs/PRODUCT_PIPELINE.md` trong cùng pull request.
