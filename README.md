# KarmaStoryAI

Biến truyện Việt Nam truyền miệng thành kịch bản kể chuyện 3 thứ tiếng (Đức/Anh/Tây Ban
Nha) cho khán giả 60+, chủ đề nhân quả + twist. Hướng A: giữ màu sắc Việt Nam, giải
thích ngắn. Mỗi kịch bản **30–40 phút** mỗi ngôn ngữ. Tách riêng với `GenImageFlowAI`
(thumbnail).

Python 3.12+, chỉ thư viện chuẩn, chạy trên Linux/macOS (khóa hàng đợi dùng `fcntl`).
Không cần `pip install`. `python3 -m karma --help` liệt kê mọi lệnh.

## Quy trình chính: bản Việt → dịch theo chương → TTS

```
nguồn (SRT) → bản Việt phóng tác (viết lại câu chữ, 3.800–5.100 tiếng)
            → grade --lang vi  (rubric + độ dài; sửa đến khi đạt)
            → translate_review.py  (glossary → dịch từng chương → review từng chương → sửa chương lỗi)
            → prep-translation  (văn bản TTS đã phiên âm tên + danh sách cảnh)
            → TTS/ảnh/video → người bản xứ nghe thử → đăng
```

Sửa nội dung ở **bản Việt** (một lần cho cả 3 ngôn ngữ), không sửa ở từng bản dịch.
Bản Việt phải là phóng tác: chỉ lấy cốt truyện làm nguyên liệu, không chép câu chữ của
kênh khác.

```bash
SRC="…/017 - Bat com de ngoai cua - vong 3 (40 phut).md"
OUT="…/017 - Ban dich vong 3"          # thư mục mới cho mỗi bản Việt mới

python3 -m karma grade "$SRC" --lang vi                                    # 1 lần gọi scorer
python3 tools/translate_review.py "$SRC" --out-dir "$OUT" --lang de --glossary-only
#   → đọc, sửa tay glossary.de.md (nhất là mục Ambiguities và Pronunciation)
python3 tools/translate_review.py "$SRC" --out-dir "$OUT" --lang all       # mặc định tối đa 2 vòng/chương
python3 -m karma prep-translation "$OUT" --lang all
python3 -m karma usage --tag "017"                                         # xem đã gọi model bao nhiêu
```

### Khi nào đạt yêu cầu

| Bước | Điều kiện đạt (code tự tính, không tin điểm/cờ pass của model) |
|---|---|
| Bản Việt (`grade --lang vi`) | rubric ≥ 8.0, mỗi tiêu chí ≥ 6.0, **và** 30–40 phút (tiếng / 130 tiếng/phút) |
| Bản dịch (`translate_review.py`) | điểm dịch ≥ 8.0, mỗi tiêu chí ≥ 6.0, mọi chương đạt, không vi phạm `avoid:` của glossary, **và** 30–40 phút |
| TTS (`prep-translation`) | chỉ chạy khi bản dịch đạt và `<lang>.md` chưa bị sửa sau review |

Sau đó vẫn cần người nghe thử bản đầu của mỗi kênh: máy chấm không thay được tai người
bản xứ.

### translate_review.py: dịch theo chương

- Mỗi lần gọi chỉ gửi **một chương** + glossary + 600 ký tự cuối chương trước, nên
  không bị cắt và không gửi lặp cả truyện. Review cũng theo chương.
- Chương chưa đạt (điểm, tiêu chí, thiếu sự kiện, vi phạm `avoid:`, thiếu tiêu đề) được
  dịch lại theo danh sách lỗi, tối đa `--max-rounds` (mặc định 2). Chương đạt thì giữ.
- Kết quả lưu trong `<lang>.chapters/`; chạy lại không gọi model. Sửa một chương nguồn
  hoặc một mục glossary thì **chỉ chương liên quan** bị dịch lại; sửa mục Pronunciation
  không dịch lại gì.
- **Chặn trước khi tốn token:** bản Việt ngoài 30–40 phút (ước tính theo tỉ lệ từ
  đích/tiếng: de 1,18, en 1,15, es 1,18) thì dừng ngay (`--ignore-length` để bỏ qua).
  Cảnh báo nếu bản Việt chưa chấm, chưa đạt hoặc đã sửa sau lần chấm.
- **Glossary** `glossary.<lang>.md` có dấu nguồn ở dòng đầu. Nếu bản Việt đã đổi, công
  cụ dừng thay vì dùng glossary cũ: xóa file, dùng `--out-dir` mới, hoặc
  `--accept-glossary`. Định dạng mỗi dòng: `- thuật ngữ Việt => cách dịch; avoid: từ sai 1, từ sai 2`
  (biến thể dưới 4 ký tự bị bỏ qua vì trùng từ thường như "Sie").
- Mục `## Pronunciation`: `- Bờm => Böm` là cách đọc cho TTS. `prep-translation` thay
  tên trong `<lang>.tts.txt` (kể cả đuôi sở hữu "Bờms"); tên Việt chưa có phát âm thì
  tự bỏ dấu và được liệt kê để bổ sung. `scenes.json` giữ chữ gốc cho phụ đề.

Đầu ra trong `--out-dir`: `glossary.<lang>.md`, `<lang>.chapters/`, `<lang>.md`,
`<lang>.review.json/.md` (điểm, thời lượng, bảng từng chương, việc còn lại, lỗ hổng của
bản nguồn), sau prep thêm `<lang>.tts.txt` và `<lang>.scenes.json`.

## Quy trình phụ: viết mới từng ngôn ngữ từ bộ xương

Dùng khi không có bản Việt hoàn chỉnh: tạo bộ xương trung tính rồi để writer viết riêng
từng ngôn ngữ (không dịch).

```bash
python3 -m karma clean "x.srt" --story 001     # .srt/.txt → stories/001/source.txt (thay nguồn cũ)
python3 -m karma skeleton 001 [--force]
python3 -m karma loop 001 --lang all [--force]  # viết → chấm → sửa theo fixes, tối đa max_rounds
python3 -m karma prep 001 --lang en
# Lệnh lẻ: write 001 --lang en [--round N --force]; score 001 --lang en --round N [--force]
```

Prompt viết nhận ngân sách từ (30–40 phút = 4.500–6.000 từ). Sai độ dài thì chưa đạt và
lời sửa "ĐỘ DÀI: cắt/viết thêm N từ" đứng đầu `fixes`. Hết `max_rounds` chưa đạt: bản
điểm cao nhất thành `<lang>.final.txt` kèm `<lang>.NEEDS_REVIEW`, `prep` từ chối. Chạy
lại dùng kết quả đã lưu. JSON chấm hỏng được giữ ở `*.score.raw.txt` (sửa tay hoặc
`score --force`). `report.md` có điểm, phút và tiêu chí yếu nhất từng vòng.

```text
stories/001/  source.txt  skeleton.md  skeleton.parts/…  en.round1.txt  en.round1.score.json
              en.final.txt  en.NEEDS_REVIEW  en.tts.txt  en.scenes.json  report.md
```

## Cấu hình

`config.json` (ghi đè theo máy bằng `config.local.json`, đã gitignore; ghi đè theo khóa
cấp đầu, nên nếu đặt `llm` phải khai báo cả writer và scorer):

| Khóa | Ý nghĩa |
|---|---|
| `target_minutes` | `[30, 40]`: khoảng thời lượng bắt buộc |
| `words_per_minute` | tốc độ đọc ước tính: de/en/es 150 từ, vi 130 tiếng. **Chưa đo thật**: chỉnh sau lần TTS đầu (giọng Đức thường 130–140) |
| `score_threshold`, `min_each_criterion` | 8.0 và 6.0 |
| `max_rounds`, `max_continuations` | số vòng viết/sửa của `loop`; số lượt nối khi bị cắt |
| `stories_dir` | đường dẫn tuyệt đối thì mọi file truyện nằm trên NAS |
| `llm.writer`, `llm.scorer` | provider: `cli`, `openai`, `codex_router` |

### Provider

- `cli` (mặc định `codex exec` / `claude -p`): prompt qua stdin, kết quả từ stdout;
  `cmd` là danh sách đối số, không qua shell.
- `openai`: API tương thích OpenAI, đọc URL/key/model từ biến môi trường
  (`base_url_env`, `key_env`, `model_env`). Không đặt key trong file cấu hình.
- `codex_router`: chạy Codex CLI thật qua Responses API của 9router, không cần đăng
  nhập OpenAI (cần Node/npm; tự dùng `npx --yes @openai/codex`). Thiết lập một lần:

  ```bash
  python3 tools/setup_9router.py --stories-dir "/home/ttien/Documents/NasSynology/YouTube/Truyen Ma VN/Kich ban"
  python3 -c 'from karma.llm import complete; print(complete("writer", "Chỉ trả lời: OK"))'
  ```

  Lệnh tạo `config.local.json` và lưu khóa ở `~/.config/karma/9router.json` (quyền
  `0600`), không ghi đè nếu đã có. Router phải hỗ trợ `/v1/responses`.

Mọi lần gọi model đi qua một hàng đợi (`work/llm.lock`), thử lại tối đa 3 lần, và ghi
vào `work/llm.log`: vai trò, nhãn truyện/ngôn ngữ, độ dài prompt/kết quả, thời gian,
trạng thái. Không ghi nội dung hay key. `python3 -m karma usage [--tag 017] [--since 2026-11-11]`
tổng hợp log này (token chỉ ước lượng = ký tự/3; số thật xem ở trang tính phí).

`prep`/`prep-translation` bỏ Markdown, viết số thành chữ (Anh `1,234.5`, Đức/Tây Ban
Nha `1.234,5`), giữ dấu kết câu trong ngoặc kép, chia đoạn ≤ 400 ký tự. Mỗi cảnh có
`chapter`, `paragraph` (chữ gốc), `tts` (đã phiên âm), `estimated_seconds`,
`image_prompt` (gợi ý để sửa). Ngày tháng, số thứ tự cần người đọc soát.

## Kiểm thử offline

```bash
python3 -m unittest
```

Test tạo workspace tạm, fake model và mock CLI/HTTP, không gọi mạng. `KARMA_ROOT` trỏ
tới workspace cấu hình khác. Đã kiểm thử bằng Python 3.14.

## Chưa làm / lưu ý

- Chưa sinh âm thanh TTS, ảnh, video, thumbnail, chưa đăng tải.
- Phản hồi review JSON hỏng của một chương trong `translate_review.py` hiện dừng cả
  lượt chạy; xóa file `<lang>.chapters/NN.rK.review.raw.txt` tương ứng rồi chạy lại.
- Mỗi ngôn ngữ một kênh riêng; nên có người bản xứ nghe bản đầu tiên.
- Kiểm tra điều khoản YouTube về nội dung do AI tạo, nội dung tái sử dụng và bản quyền
  ảnh/nhạc.
