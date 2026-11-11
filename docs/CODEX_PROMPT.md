# Prompt giao cho Codex: hoan thien KarmaStoryAI

## Vai tro
Ban la ky su Python. Hay hoan thien du an trong thu muc hien tai (`KarmaStoryAI`) theo dac ta duoi day.
Dung Python 3.12, CHI thu vien chuan tru khi that su can (neu can thi ghi vao requirements.txt). Khong dung framework nang.
Doc truoc: README.md, config.json, rubric.md, prompts/*, tools/clean_srt.py. Giu nguyen va tai su dung chung.

## Muc tieu
Bien truyen Viet Nam truyen mieng thanh kich ban 3 thu tieng (de/en/es) cho khan gia 60+, chu de luat nhan qua + twist bat ngo,
huong A (giu mau sac Viet Nam, giai thich ngan). Quy trinh:

truyen VN -> BO XUONG -> viet rieng tung ngon ngu -> cham diem -> >= 8.0 thi giu, chua dat thi viet lai theo `fixes` -> kich ban cuoi

KHONG dich tu tieng Viet sang ngon ngu khac: moi ngon ngu viet moi tu bo xuong.
Khong sao chep cau chu cua nguon.

## Can lam
Tao CLI `python3 -m karma <lenh>` (package `karma/`, diem vao `karma/__main__.py`, moi lenh 1 file `karma/cli_*.py`):

1. `clean <file.srt|file.txt> --story <id>`
   Goi logic cua tools/clean_srt.py (import duoc, khong chay subprocess), luu `stories/<id>/source.txt`.

2. `skeleton <id>`
   Doc `stories/<id>/source.txt`, dien prompts/skeleton.md ({{story}}), goi model viet, luu `stories/<id>/skeleton.md`.
   Truyen dai thi chia khuc (~3000 tu) roi gop lai. Khong ghi de skeleton.md da co tru khi co `--force`.

3. `write <id> --lang de|en|es|all`
   Dien prompts/write_<lang>.md ({{skeleton}}, {{minutes}} lay tu config.target_minutes, {{fixes}} rong o vong 1).
   Luu `stories/<id>/<lang>.round<N>.txt`. Kich ban dai: viet theo tung chuong ("## Chapter N") neu model cat giua chung.

4. `score <id> --lang <l> --round N`
   Dien prompts/score.md ({{lang}}, {{rubric}} = rubric.md, {{skeleton}}, {{script}}), goi model, PARSE JSON
   (chiu duoc ```json fence va chu thua quanh JSON). Kiem tra: co du 6 tieu chi, diem 0-10.
   TU TINH LAI `score` = trung binh co trong so theo rubric.md va `pass` = score >= config.score_threshold
   va moi tieu chi >= config.min_each_criterion (khong tin con so model tu bao). Luu `<lang>.round<N>.score.json`.

5. `loop <id> --lang de|en|es|all`   (lenh chinh)
   Lap: write -> score; neu khong pass thi viet lai voi {{fixes}} = danh sach `fixes` + ban nhap truoc, toi da config.max_rounds.
   Pass thi copy ra `<lang>.final.txt`. Het vong ma chua pass thi luu ban DIEM CAO NHAT thanh `<lang>.final.txt`
   va ghi `<lang>.NEEDS_REVIEW` (kem ly do). Co ghi `stories/<id>/report.md`: diem tung vong, tieu chi yeu nhat, ket qua.
   Chay lai la tiep tuc (bo qua vong da co file), khong goi lai model cho thu da co. Co `--force` de lam lai tu dau.

6. `prep <id> --lang <l>`  (sau khi pass)
   Chuan bi cho TTS: bo ky hieu/markdown, viet so thanh chu, them dau ngat; xuat `<lang>.tts.txt`
   (chia thanh cac doan <= ~400 ky tu, moi doan 1 dong de TTS tung doan va cache duoc) va `<lang>.scenes.json`
   (danh sach canh: chuong, doan van, uoc luong giay = so tu/150*60, y tuong prompt hinh de nguoi dung sua).

## Goi model (quan trong)
Khong ghi cung provider. Tao `karma/llm.py` voi ham `complete(role, prompt) -> str`, `role` la "writer" hoac "scorer".
Cach goi cau hinh trong config.json, mac dinh:
- writer: chay lenh `codex exec` (prompt qua stdin hoac doi so; doc stdout) - hoac API tuong thich OpenAI qua
  bien moi truong ROUTER_URL, ROUTER_KEY, ROUTER_MODEL (9router).
- scorer: chay lenh `claude -p` (Claude Code che do khong tuong tac, prompt qua stdin, doc stdout).
Cho phep doi bang config.json: `{"writer": {"type": "cli", "cmd": ["codex","exec"]}, "scorer": {"type": "cli", "cmd": ["claude","-p"]}}`
hoac `{"type": "openai", "base_url_env": "...", "key_env": "...", "model_env": "..."}`.
Co timeout, thu lai toi 3 lan voi cho tang dan, bao loi ro rang. KHONG ghi API key vao file/commit.
Moi lan goi ghi log (role, do dai prompt, thoi gian, thanh cong/that bai) vao `work/llm.log` (da .gitignore).

## Yeu cau chat luong
- Moi buoc luu ra file trong `stories/<id>/` de xem lai; khong mat du lieu khi bi ngat giua chung.
- Khong chay song song nhieu lenh goi model (de tranh quota/khoa). Hang doi tuan tu.
- Thong bao tieng Viet, ten bien/ham tieng Anh. Code ngan gon, moi ham 1 viec.
- Khong de lo noi dung nguon: prompt viet khong duoc chua cau chu goc dai hon bo xuong can thiet.
- Khong them tinh nang ngoai danh sach tren (khong lam TTS/anh/video o dot nay).

## Kiem thu (bat buoc, chay offline)
Tao `tests/` (unittest hoac pytest) voi model GIA (fake `llm.complete`):
- parse JSON cham diem: JSON sach, co ```json fence, co chu thua, thieu tieu chi -> loi ro.
- tinh lai score/pass: model noi pass nhung tieu chi < 6 -> van fail.
- `loop`: fake writer/scorer, vong 1 fail vong 2 pass -> final.txt la ban vong 2; luon fail -> final = ban diem cao nhat + NEEDS_REVIEW.
- chay lai `loop` khong goi model cho vong da co.
- clean_srt: giu nguyen hanh vi hien tai.
`python3 -m unittest` phai chay xanh. Neu khong chay duoc lenh that (khong co codex/claude) thi noi ro, dung fake.

## Hoan thanh khi
- Chay duoc: `python3 -m karma clean x.srt --story 001`, `skeleton 001`, `loop 001 --lang all` voi fake LLM, ra du file va report.md.
- Cap nhat README.md: muc "Da co" / "Chua lam" cho dung, huong dan dung tung lenh, cach cau hinh llm.
- Tom tat cuoi: file da tao, lenh nao chay duoc, lenh nao CHUA kiem tra voi model that.
