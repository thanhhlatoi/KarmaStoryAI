# KarmaStoryAI

## Dịch bản Việt và review đối chiếu

Khi muốn dịch từ một bản Việt đã có (khác quy trình viết mới từ bộ xương):

```bash
python3 tools/translate_review.py "/duong/dan/ban-viet.md" --out-dir "/duong/dan/NAS/ban-dich" --lang all
```

Chạy tuần tự de/en/es: writer dịch toàn bộ, scorer review đối chiếu bản Việt.
Mỗi ngôn ngữ có bản dịch `*.round1.md`, review Markdown, JSON và phản hồi gốc.
Chạy lại bỏ qua bản dịch/review đã lưu, tiếp tục draft nếu bị ngắt. Bản dịch chưa
được tự động sửa theo review. Điểm dịch thuật dùng bộ tiêu chí riêng: trung thành
30%, tự nhiên 25%, đọc thành tiếng 20%, rõ văn hóa 15%, nhất quán 10%.
Lỗi cốt truyện sẵn có ở nguồn được ghi riêng, không coi là lỗi dịch.

## Kết nối Codex CLI qua 9router

Writer hỗ trợ `type: "codex_router"`: chạy Codex CLI thật qua Responses API
của 9router, không cần đăng nhập OpenAI. Scorer dùng Claude CLI đã đăng nhập.
Node/npm phải có sẵn; nếu chưa cài Codex, tool dùng `npx --yes @openai/codex`.

Thiết lập từ kết nối 9router có sẵn (chỉ đọc, không sửa cấu hình nguồn):

```bash
python3 tools/setup_9router.py --stories-dir "/home/ttien/Documents/NasSynology/YouTube/Truyen Ma VN/Kich ban"
```

Lệnh thiết lập tạo `config.local.json` (được gitignore) để ghi đè cấu hình máy
và lưu khóa riêng ở `~/.config/karma/9router.json`, quyền `0600`.
Không ghi khóa vào README hoặc config được commit. Chạy lại khi file local đã có
sẽ báo lỗi để tránh ghi đè. `stories_dir` tuyệt đối đưa mọi file truyện sang NAS.
Ghi đè local áp dụng theo khóa cấp đầu: nếu đặt `llm` cần khai báo cả writer/scorer.

Kiểm tra writer thực tế (một lần gọi model):

```bash
python3 -c 'from karma.llm import complete; print(complete("writer", "Chỉ trả lời: OK"))'
```

Provider yêu cầu router hỗ trợ `/v1/responses`. Đầu ra được đọc từ file cuối
của Codex để tránh lẫn banner và tiến độ; timeout writer hiện đặt 900 giây.

Bien truyen Viet Nam truyen mieng thanh kich ban 3 thu tieng (Duc/Anh/Tay Ban Nha) cho khan gia 60+,
chu de luat nhan qua + twist bat ngo. Huong A: giu mau sac Viet Nam, giai thich ngan.
Tach rieng voi du an `GenImageFlowAI` (tao thumbnail).

## Quy trinh

```
truyen VN -> BO XUONG (trung tinh ngon ngu) -> viet rieng tung ngon ngu (Codex) -> cham (Claude) -> >=8 -> TTS/anh/video -> dang
                                                       ^______ fixes ______|  (toi da max_rounds)
```

KHONG dich: moi ngon ngu viet moi tu bo xuong. Chi lay cot truyen lam nguyen lieu, khong chep cau chu cua kenh khac.

## Cau truc
```
config.json        ngon ngu, nguong diem (8.0), so vong toi da, do dai
rubric.md          tieu chi cham + trong so
prompts/           skeleton.md, write_{de,en,es}.md, score.md   (dien {{...}} roi gui model)
stories/<id>/      skeleton.md, <lang>.round1.txt, <lang>.round1.score.json, ... , <lang>.final.txt
tools/clean_srt.py lam sach phu de tu dong YouTube -> van ban lien mach
```

## Da co
- CLI `python3 -m karma` với đủ `clean`, `skeleton`, `write`, `score`, `loop`, `prep`.
- Tái sử dụng `tools/clean_srt.py`, không thay đổi hành vi làm sạch phụ đề.
- Bộ xương chia nguồn thành các phần khoảng 3.000 từ, lưu từng phần và tổng hợp.
- Viết mới từng ngôn ngữ từ bộ xương; tiếp tục theo chương khi câu trả lời bị cắt.
- Chấm JSON có fence/chữ thừa; kiểm tra đủ 6 tiêu chí và tự tính điểm theo `rubric.md`.
- Vòng lặp viết/sửa, chọn bản đạt hoặc bản có điểm cao nhất, báo cáo và cờ cần duyệt.
- Provider CLI/API tùy cấu hình; khóa tuần tự liên tiến trình, timeout, tối đa 3 lần thử.
- Chuẩn bị văn bản TTS de/en/es và danh sách cảnh, không gọi model ở bước `prep`.
- Kiểm thử offline bằng fake LLM, dùng thư viện chuẩn, không cần cài dependency.

## Chua lam
- Sinh âm thanh TTS, ảnh, video, thumbnail và đăng tải.
- Chưa kiểm chứng chất lượng nội dung với model thật hay người bản ngữ.

## Yêu cầu và bắt đầu

Code dành cho Python 3.12+, dùng thư viện chuẩn. Chạy tại thư mục gốc dự án trên
Linux/macOS (khóa hàng đợi dùng `fcntl`). Không cần `pip install`.

```bash
python3 -m karma --help
python3 -m karma clean "x.srt" --story 001
python3 -m karma skeleton 001
python3 -m karma loop 001 --lang all
python3 -m karma prep 001 --lang en
```

`clean` nhận cả `.srt` và `.txt`, ghi `stories/001/source.txt`. Lệnh này thay thế
nguồn nếu đã tồn tại. Sau khi đổi nguồn, chạy lại `skeleton --force` và `loop --force`.
Mã truyện chỉ chứa chữ ASCII, số, dấu `-` hoặc `_`.

### Từng lệnh

```bash
# Không ghi đè bộ xương đã có; --force tạo lại.
python3 -m karma skeleton 001 --force

# Viết riêng: mặc định chọn vòng mới, hoặc tiếp tục bản dở.
python3 -m karma write 001 --lang en
python3 -m karma write 001 --lang all
python3 -m karma write 001 --lang en --round 1 --force

# Chấm riêng một vòng; dùng --force nếu cần gọi lại model chấm.
python3 -m karma score 001 --lang en --round 1
python3 -m karma score 001 --lang en --round 1 --force

# Lệnh chính: viết → chấm → sửa theo fixes + bản nháp trước.
python3 -m karma loop 001 --lang en
python3 -m karma loop 001 --lang all

# Làm lại từ đầu các vòng của ngôn ngữ được chọn.
python3 -m karma loop 001 --lang en --force

# Chỉ chạy khi bản cuối khớp một vòng đã chấm đạt.
python3 -m karma prep 001 --lang en
```

`loop` chạy tuần tự de/en/es. Chạy lại sẽ dùng các vòng viết/chấm đã lưu và tiếp
tục bước còn thiếu, không gọi lại model cho kết quả đã có. Nếu JSON chấm không hợp
lệ, phản hồi thô được giữ trong `*.score.raw.txt`; sửa file đó rồi chạy lại hoặc
dùng `score --force` để chấm lại. `loop --force` xóa các vòng, bản cuối, cờ duyệt và
file prep của ngôn ngữ được chọn; giữ nguồn và bộ xương.

Đạt khi tổng điểm >= `score_threshold` **và** mọi tiêu chí >= `min_each_criterion`
**và** thời lượng ước tính nằm trong `target_minutes` (mặc định 30–40 phút).
Thời lượng do code đo: số từ (bỏ dòng tiêu đề) / `words_per_minute` của ngôn ngữ
(mặc định 150; chỉnh lại sau khi đo bản TTS thật). Sai độ dài thì chưa đạt, và lời
sửa "ĐỘ DÀI: cắt/viết thêm N từ" được đưa lên đầu danh sách `fixes` cho vòng sau.
Prompt viết nhận sẵn ngân sách từ, ví dụ 30–40 phút = 4.500–6.000 từ.
Điểm và cờ pass do model khai báo không được sử dụng. Hết `max_rounds` mà chưa đạt,
bản điểm cao nhất trở thành bản cuối kèm `NEEDS_REVIEW`; `prep` sẽ từ chối bản này.
`report.md` liệt kê điểm, tiêu chí yếu nhất từng vòng và kết quả.

### File đầu ra

```text
stories/001/
  source.txt
  skeleton.parts/<content-hash>/001.md   # checkpoint nguồn dài
  skeleton.md
  en.round1.draft.txt                   # chỉ tồn tại khi viết chưa xong
  en.round1.txt
  en.round1.score.raw.txt
  en.round1.score.json
  en.final.txt
  en.NEEDS_REVIEW                       # chỉ khi chưa đạt
  en.tts.txt
  en.scenes.json
  report.md
```

File văn bản/JSON được ghi nguyên tử. Mỗi phản hồi viết được lưu vào bản dở trước
khi gọi tiếp. Model được yêu cầu kết thúc bằng `[[END_SCRIPT]]`; marker được bỏ
khỏi bản hoàn chỉnh. Nếu quá giới hạn `max_continuations` (mặc định 8 lượt nối thêm
mỗi lần chạy), lệnh báo lỗi và giữ bản dở để tiếp tục.

`prep` bỏ Markdown, viết số đếm/thập phân thành chữ, bảo đảm dấu kết câu, chia
đoạn tối đa 400 ký tự theo dấu câu/khoảng trắng. Mỗi dòng TTS khớp một mục cảnh gồm
`chapter`, `paragraph`, `estimated_seconds` (số từ / 150 × 60), `image_prompt`.
Prompt hình là ý tưởng ban đầu để người dùng sửa. Số dùng quy ước Anh `1,234.5`,
Đức/Tây Ban Nha `1.234,5`; ngày tháng, số thứ tự và cách đọc số theo ngữ cảnh cần
người dùng đọc soát.

## Cấu hình LLM

Trong `config.json`, mặc định:

```json
"llm": {
  "writer": {"type": "cli", "cmd": ["codex", "exec"], "timeout": 300, "attempts": 3},
  "scorer": {"type": "cli", "cmd": ["claude", "-p"], "timeout": 300, "attempts": 3}
}
```

Cài và đăng nhập CLI tương ứng trước khi chạy. Prompt đi qua stdin, kết quả lấy
từ stdout; `cmd` là danh sách đối số, không chạy qua shell. Có thể thêm đối số
model vào `cmd` tùy CLI. Cấu hình `writer`/`scorer` trực tiếp ở cấp gốc cũng được
hỗ trợ nếu không có mục tương ứng trong `llm`.

Để writer dùng API tương thích OpenAI (9router), thay mục `llm.writer` bằng:

```json
{
  "type": "openai",
  "base_url_env": "ROUTER_URL",
  "key_env": "ROUTER_KEY",
  "model_env": "ROUTER_MODEL",
  "timeout": 300,
  "attempts": 3,
  "max_tokens": 8192
}
```

Đặt `ROUTER_URL` trong môi trường thành base URL, ví dụ
`http://127.0.0.1:20128/v1` (dùng đúng địa chỉ router của bạn), `ROUTER_KEY` thành
API key và `ROUTER_MODEL` thành mã model. Scorer cũng có thể dùng cấu hình OpenAI
với các tên biến riêng. Không đặt key trong file cấu hình hay commit.

Mỗi lần thử ghi role, độ dài prompt, thời gian, trạng thái vào `work/llm.log`;
không log nội dung/key. Các lần thử đợi tăng dần 1 rồi 2 giây. `work/` đã được
gitignore. Mọi lần gọi model dùng chung khóa `work/llm.lock` để tránh chạy song song.
Không đưa nguồn đầy đủ vào prompt viết; scorer chỉ nhận bộ xương và kịch bản nên
không xác minh được sao chép so với nguồn gốc.

## Kiểm thử offline

```bash
python3 -m unittest
```

Các test tạo workspace tạm, fake `llm.complete` và mock CLI/HTTP, không gọi mạng
hay model thật. Bao gồm JSON, trọng số/pass, vòng lặp fail/pass, chọn bản tốt nhất,
cache/chạy tiếp, nguồn dài, viết bị cắt, clean SRT/TXT, prep và quy trình CLI cả
ba ngôn ngữ. Có thể đặt `KARMA_ROOT` để chạy với workspace cấu hình khác.

Môi trường triển khai hiện kiểm thử bằng Python 3.14.4; chưa có Python 3.12 và
`codex` để chạy kiểm chứng trực tiếp. Chưa gọi Claude/API model thật.

## Luu y
- Moi ngon ngu 1 kenh rieng; nen co nguoi ban xu doc lai ban dau tien.
- Kiem tra dieu khoan YouTube ve noi dung do AI tao va ban quyen anh/nhac.
