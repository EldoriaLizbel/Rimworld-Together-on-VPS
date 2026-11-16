# รายงานส่งมอบ: การเตรียม RimWorld Together on VPS

ขอบเขต: working copy, โค้ด workflow และการทดสอบกับ Docker โปรเจกต์ชั่วคราว ไม่ได้ push, เปิด firewall, เปลี่ยน DNS, ตั้ง GitHub Secrets หรือเชื่อมต่อ production VPS

## A. ผลตรวจ repository

| ระดับ | ตำแหน่งและสาเหตุ | ผลกระทบ | การแก้และหลักฐาน |
| --- | --- | --- | --- |
| Critical | `002_seed_superuser.sql` มี `DELETE FROM public.user_profile` ก่อนสร้าง seed | หากนำไฟล์ init ไปรันซ้ำ บัญชี dashboard เดิมหายได้ | Seed เฉพาะฐานว่าง; integration สร้างบัญชีเดิมจำลองแล้วตรวจว่ายังอยู่หลัง migration และ restore |
| High | `deploy.sh` รัน SQL 003–006 ทุกครั้ง ไม่มี ledger หรือ checksum | บอกไม่ได้ว่าฐานอยู่ schema ใด; คำสั่งเปลี่ยน role/password อาจถูกรันซ้ำและ deploy ย้อนผิดรุ่น | ตรวจตาราง/สิทธิ์ก่อน baseline, advisory lock, checksum และ transaction ต่อ migration; ทดสอบฐานใหม่ ฐานเดิม รันซ้ำ และจงใจแก้ checksum ให้ล้มเหลว |
| High | `frontend_1/package-lock.json` ใช้ [Next.js 14 ซึ่งอยู่นอกระยะรองรับ](https://nextjs.org/support-policy); `apps/api/requirements.txt` ตรึง msgpack เดิม | npm รายงาน high/critical และ pip-audit พบ advisory ในตัวถอดข้อมูลเซฟ | Next.js 16.4.6/React 19, msgpack 1.2.3; build/REST flow ผ่าน และทดสอบตัวถอด MessagePack/LZ4 |
| High | Image เว็บเดิมใช้ Node base ที่รวม npm CLI และ dependencies ใน runtime | Trivy พบ high ที่มีรุ่นแก้ในแพ็กเกจของ npm CLI แม้แอปไม่เรียก npm ตอนรัน | ใช้ Node base เฉพาะ build; runtime คัดลอก Node executable และ standalone app เท่านั้น สแกนซ้ำผ่าน gate |
| High | `deploy.sh` build/start ทั้ง stack และไม่มี managed backup/rollback | การแก้ dashboard อาจกระทบเกม; กู้สถานะหลัง deploy ไม่ผ่านได้ยาก | แยก scope, dry run, เก็บ image รุ่นเดิม, ทำ backup ตามความเสี่ยง; timed integration เปรียบเทียบ container ID และเวลาเริ่มของเกม/API/DB และทดสอบ rollback หลังเว็บจำลองเปิดไม่ขึ้น |
| Medium | `frontend_1/app/api/` ไม่ได้บังคับ origin สม่ำเสมอ, login ไม่มีเพดาน, logout เดิมล้าง cookie อย่างเดียว | การลองล็อกอินซ้ำใช้ CPU; token เดิมใช้ได้จนหมดอายุถ้าคัดลอกไว้ | Same-origin guard ทุก write, cap ต่อบัญชีและทั้งระบบ, cookie ใหม่ทุก login, server-side revocation, bounded JSON, no-store/security headers ทดสอบด้วย HTTP จริง |
| Medium | `apps/api/main.py` ใช้ dialog ฝั่ง browser สำหรับยืนยันคำสั่ง และ file readers มีบางจุดอ่านไฟล์ไม่จำกัด | ผู้มีสิทธิ์เรียก API พลาดได้; ไฟล์ที่ผิดรูปอาจรบกวนการอ่าน | ยืนยันใน API, จำกัด file size, ปฏิเสธ path ที่ชี้ผ่าน symlink, atomic replace และ undo สำหรับ I/O failure ที่ย้อนกลับได้; ทดสอบ admin/regular user และ fixture ไฟล์ |
| Medium | `compose.yaml` ตรวจ web แค่ตอบ 200 และ log rotation หลักใช้เฉพาะเกม | สถานะ Healthy ไม่ยืนยัน dependency สำคัญ และ log อาจโต | Authenticated DB probe, Dashboard → API/DB, game heartbeat/TCP สอดคล้องกับ snapshot, rotation ทุกบริการ; ตรวจ runtime ใน Docker โปรเจกต์ชั่วคราว |
| Low | `RTenv.txt` อ้าง worker/nginx แยกที่ไม่ได้เปิดใช้งาน | คู่มือและการตรวจพอร์ตสับสน | อัปเดต topology จริงและตัวแปร; ตรวจ Compose ทั้ง dev และ production |

Dependency map: browser → web → api/PostgreSQL; api → PostgreSQL และอ่าน game data/bridge; เกมเขียน world/saves/bridge โดยไม่ต้องพึ่ง DB; Beekeeper → PostgreSQL (optional). Compose ใช้ network เดิมและคง persistent volumes กับ bind mount เดิม. Production build ไม่ต้องใช้ secret; DB/FastAPI ไม่มี published port.

## B. ไฟล์ที่เปลี่ยน

- เพิ่ม `.github/workflows/{ci,release,deploy-production}.yml` และ `.github/dependabot.yml` สำหรับ quality gate, GHCR และ manual CD
- เพิ่ม `scripts/{ops,db,safe_backup,release-manifest}.py`, `scripts/smoke-game.py`, `scripts/smoke-web.cjs` และ shell entry points: `preflight`, `migrate`, `backup`, `verify-backup`, `restore`, `deploy-release`, `rollback`, `smoke-test`, `release-status`, `ssh-deploy`
- เพิ่ม `compose.prod.yaml`, `apps/api/.dockerignore`, `infra/beekeeper/.dockerignore` และ `007_dashboard_security.sql` เพื่อแยก registry images, ตัดไฟล์ที่ไม่จำเป็นจาก build context และเพิ่มตาราง session/login budget
- เพิ่ม `pyproject.toml`, `tests/`, `frontend_1/eslint.config.mjs`, `frontend_1/tests/` และตัวช่วย `frontend_1/src/server/request-security.mjs`
- แก้ `deploy.sh`, `compose.yaml`, environment examples และ ignore/line-ending rules; แก้ Dockerfile เว็บ/API/Beekeeper, Python API/supervisor/parser, frontend auth/API routes/config และ JSX สำหรับส่งการยืนยัน; แก้ SQL seed ให้รักษาบัญชีเดิม
- แก้ `README.md`, `RTenv.txt` และเพิ่ม `docs/operations.md`, `docs/github-actions.md` และรายงานนี้
- ไม่ได้ลบไฟล์หรือข้อมูลเดิมที่ต้องใช้กับ deployment.

## C. CI/CD

PR เข้า `main` และ push เข้า `main` ทำ lint, tests, dependency audit, secret scan, Compose validation และสร้าง stack ชั่วคราวใน Docker. เฉพาะ push เข้า main ที่ผ่านทุก job จะเข้าสร้างและสแกน Linux amd64 images แล้ว publish ใน GHCR พร้อม manifest ที่บันทึก SHA และ image digests. ถ้า gate หรือ image scan ที่บังคับไม่ผ่าน จะไม่มี release manifest สำหรับ deploy.

Production ใช้ **Deploy production (manual)**, รับ SHA เต็มและ scope ที่กำหนดและเริ่มต้นด้วย dry run. SSH บังคับตรวจ host key และรองรับ forced command บน VPS. GitHub concurrency และไฟล์ล็อกบนโฮสต์ป้องกันงานซ้อน. การอนุมัติจากผู้ตรวจขึ้นอยู่กับ Environment ที่ผู้ดูแลตั้งจริง.

## D. Deploy

- Fresh: `sh deploy.sh` หรือ `sh deploy.sh --prepare` ตามด้วย release ที่เผยแพร่แล้ว
- Existing: อัปเดต checkout โดยรักษา `.rwt-deploy` เดิม และเลือก `--scope app` สำหรับการเปลี่ยนสัญญา Web/API ครั้งแรกโดยให้เกมทำงานต่อ
- Web/API แยกได้ด้วย `--scope web` หรือ `--scope api`; เกมใช้ `--scope rimworld --maintenance` ซึ่งต้องมี verified backup ก่อนใช้ image ใหม่
- Preflight ตรวจ Docker/Compose, architecture, env, bind/port, RAM/disk, persistence path และ Compose model. Dry run แสดง scope, schema, backup และ smoke โดยไม่เปลี่ยนสแตก. การ pull จริงยืนยัน registry access และ digest ก่อนหยุดบริการ.
- Release เดิมที่ image/config ตรงกันและ healthy เป็น no-op. `release-status.sh` แสดงสถานะปัจจุบันและ backup ล่าสุด.

## E. Data safety

```sh
sh scripts/backup.sh --scope db
sh scripts/backup.sh --scope full --maintenance
sh scripts/verify-backup.sh <BACKUP_ID>
sh scripts/restore.sh <BACKUP_ID> --new-project rwt-recovery --confirm <BACKUP_ID> --start
sh scripts/rollback.sh --scope web
```

Backup ใช้ PostgreSQL custom dump และ archive ของเกม/bridge (full), บันทึก checksum, ขนาด, major schema/game และรุ่น image ใน `.rwt-deploy/backups` หรือที่กำหนด. Restore ตรวจไฟล์ก่อนขอ scope ใหม่ ใช้ฐาน/โฟลเดอร์/พอร์ตแยกและต้องพิมพ์ ID เดิม. Rollback ย้อน application image เมื่อ schema รองรับ ไม่ย้อนฐานโดยอัตโนมัติ. ข้อมูลหลังเวลาของ snapshot ไม่อยู่ใน backup; การกู้ active world จำเป็นต้องให้ผู้ดูแลตรวจแล้วเลือก cutover.

## F. การทดสอบที่รัน

| คำสั่ง/การตรวจ | ผล |
| --- | --- |
| `npm run lint`, `npm test`, `npm audit --audit-level=high` | ผ่าน, 4 tests, ไม่มี advisories จาก npm audit |
| `npm ci` / `npm run build` ใน Docker build | ผ่าน โดยไม่ส่งไฟล์ .env เข้า build context |
| `ruff check apps/api scripts tests`, `pytest -q`, `pip-audit -r apps/api/requirements.txt`, `bandit -q -ll -r apps/api` | ผ่าน, 16 tests, ไม่มี advisories จาก pip-audit และไม่พบ Bandit ระดับ medium/high |
| `sh -n`, ShellCheck, actionlint, Gitleaks แบบ redacted | ตรวจ syntax และ workflow; ไม่ส่ง credential จริงเข้าการทดสอบ |
| `python3 tests/compose_check.py` | ผ่านทั้ง Compose dev และ production ที่ดึงด้วย digest |
| `python3 -u tests/integration.py` | ผ่านบน Docker Linux x86-64: fresh stack, legacy baseline, checksum fail ที่ตั้งใจ, login/logout/rate limits, no-op, web/API/game scopes, maintenance prompt, failure rollback, local game TCP และ backup/restore |
| Trivy 0.71.2 image scanning | เว็บและ API ไม่พบ high/critical ที่มีรุ่นแก้ตามเกณฑ์ gate; upstream images มีรายการแยกด้านล่าง |

ระหว่างพัฒนาเจอปัญหาเงื่อนไข ledger ว่าง, การตรวจ no-op และการ sync ไฟล์ backup บน Windows; แก้แล้วและรัน integration ซ้ำ. ทดสอบด้วย fixture บัญชี/ไฟล์เซฟ และเกม binary จริงใน container ไม่ได้ใช้ฐานจริงหรือล็อกอินด้วยตัวเกมจริง. การ bootstrap apt บน Ubuntu VPS เปล่า, GHCR publish และ SSH ไป production ยังไม่ถูกเรียกจริง.

## G. สิ่งที่ต้องตั้งเอง

- ให้ Actions เขียน Releases/Packages และให้ VPS อ่าน GHCR packages; ตั้ง branch protection และ `production` Environment/Required reviewers ใน GitHub
- ตั้ง `VPS_HOST`, `VPS_SSH_USER`, `VPS_SSH_PRIVATE_KEY`, `VPS_SSH_KNOWN_HOSTS`, และ `VPS_SSH_PORT` หากไม่ใช่ 22 ตาม [คู่มือ GitHub Actions](github-actions.md)
- ตรวจ IP จากผู้ให้บริการ ตั้ง SSH/key แบบจำกัด เปิด TCP 25555 ตามต้องการ และจัดที่เก็บ backup ที่เข้ารหัสนอก VPS. เปิด TCP 10005 เฉพาะเมื่อผู้ดูแลเลือกเปิด dashboard แต่ HTTP ยังไม่เข้ารหัส.

## H. ความเสี่ยงที่เหลือ

Trivy รายงาน finding ระดับ high/critical ใน images ที่รับจาก upstream: RimWorld wrapper 145 รายการ (31 มีรุ่นแก้), Beekeeper wrapper 157 (12 มีรุ่นแก้), PostgreSQL 175 (62 มีรุ่นแก้). ตัวเลขนับรายการจาก scanner รวมกรณีซ้ำตามแพ็กเกจ/targets และไม่ได้สรุปว่าเส้นทางโจมตีเข้าถึงได้จริงในระบบนี้. บางรายการอยู่ใน .NET runtime ใน binary เกมหรือใน Go binary ที่มากับ PostgreSQL image. Workflow แสดงรายการ upstream โดยไม่อัปเกรด binary/ฐานข้อมูลเอง; ให้ตรวจรายการจริงและเลือก patch ที่ผ่าน compatibility ก่อนเปิดระบบสู่ผู้ใช้. Beekeeper ปิดได้ และ PostgreSQL/API ไม่มี public port.

การอัปเกรดเกมเป็นงาน maintenance แยกและต้องทดสอบความเข้ากันได้กับม็อดและเซฟจริง. อัปเกรด PostgreSQL 16.x ของระบบเก่าผ่านขั้นตอนแยกหลัง backup เพื่อหลีกเลี่ยงการรีสตาร์ต DB จากการอัปเดตเว็บ. เก็บ backup นอก VPS เพื่อรับมือ disk/host สูญหาย. ระบบไม่สามารถพิสูจน์ NAT, cloud firewall, client handshake หรือการโหลดโลกจริงจาก TCP อย่างเดียว.

## I. สถานะความพร้อม

| ด้าน | สถานะ |
| --- | --- |
| Code Ready | ผ่านการทดสอบ working copy และ stack ชั่วคราว |
| CI Ready | quality gate commands และ workflow lint ตรวจในเครื่อง; GitHub-hosted run ยังไม่รัน |
| Release Build Ready | สร้าง image Linux amd64 ในเครื่อง; ยังไม่ publish GHCR |
| CD Config Ready | มี manual workflow, SSH protocol และคู่มือ; Environment/Secrets ยังไม่ได้ตั้ง |
| VPS Deployment Verified | ยังไม่ได้ deploy บน Ubuntu 22.04 VPS |
| Backup Verified / Restore Verified | ผ่านจริงในโปรเจกต์ชั่วคราว |
| Rollback Verified | ผ่านทั้ง manual web rollback และ automatic rollback หลัง health failure ในโปรเจกต์ชั่วคราว |
| External Game Connectivity Verified | ตรวจ TCP ผ่านเฉพาะภายใน Docker และพอร์ตเครื่องทดสอบ |
| Actual Game Client Join Verified | ยังไม่ได้ทดสอบด้วย RimWorld client |
