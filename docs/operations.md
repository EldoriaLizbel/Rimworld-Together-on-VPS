# คู่มือดูแล RimWorld Together บน VPS

ใช้กับ Ubuntu Server 22.04 x86-64, Docker Engine และ Docker Compose 2.24.4 ขึ้นไป โดยมี Python 3.10+ บนโฮสต์สำหรับคำสั่งดูแลระบบ แอปใช้ runtime ใน container ของตัวเอง แนะนำ RAM อย่างน้อย 4 GiB เป็นจุดเริ่มต้น และเผื่อพื้นที่ให้ world, saves และ backup ตามการใช้งานจริง

## ติดตั้งหรืออัปเดต

| งาน | คำสั่งจาก root ของ checkout |
| --- | --- |
| ติดตั้งจากซอร์สแยกขาดจาก GHCR | `sh deploy.sh` |
| เตรียม Docker และไฟล์ส่วนตัวโดยยังไม่เริ่มบริการ | `sh deploy.sh --prepare` |
| ตรวจเครื่องและพอร์ต | `sh scripts/preflight.sh` (เพิ่ม `--version <SHA40>` เพื่อตรวจ registry แบบอ่านอย่างเดียว) |
| ดูแผนสำหรับการอัปเดต | `sh scripts/deploy-release.sh --version <SHA40> --scope web --dry-run` |
| อัปเดต dashboard อย่างเดียว | `sh scripts/deploy-release.sh --version <SHA40> --scope web` |
| ย้าย dashboard และ API รุ่นเดิมเข้าสู่ระบบ release | `sh scripts/deploy-release.sh --version <SHA40> --scope app` |
| อัปเดต API หลังผ่านการย้ายครั้งแรก | `sh scripts/deploy-release.sh --version <SHA40> --scope api` |
| อัปเดตเกมในเวลาปิดให้บริการ | `sh scripts/deploy-release.sh --version <SHA40> --scope rimworld --maintenance` |
| ติดตั้ง release ทั้งชุด | `sh scripts/deploy-release.sh --version <SHA40> --scope all` |
| อัปเดตทั้งชุดเมื่อมีการเปลี่ยนเกม | เพิ่ม `--maintenance` |
| อัปเดตจากซอร์สเฉพาะบริการ | `python3 scripts/ops.py bootstrap --scope app` (หรือ `web`, `api`, `rimworld`, `beekeeper`) |

ระบุ SHA เต็ม 40 ตัวจาก Release ของ GitHub คำสั่งจะอ่าน manifest ตรวจความเข้ากันได้และดึง image ด้วย digest โดยใช้การตั้งค่าจาก `.rwt-deploy/compose.env` เฉพาะโปรเจกต์เดิม ไม่เปลี่ยนรหัสผ่าน ฐานข้อมูล หรือที่อยู่ไฟล์เกม

สำหรับผู้ใช้รุ่นเดิม ให้รักษา `.rwt-deploy/` และ volume เดิม อัปเดต checkout ด้วย `git pull --ff-only origin main` หลังตรวจ diff จากนั้นเลือก `--scope app` เพื่ออัปเดต dashboard/API โดยไม่หยุดเกม ระบบสำรองฐานข้อมูลก่อนใช้ migration ใหม่เมื่อจำเป็น รุ่นใหม่ใช้ session แบบเก็บสถานะในฐานข้อมูล ผู้ใช้ต้องลงชื่อเข้าใช้ใหม่หลังการอัปเดตครั้งแรก บัญชีและรหัสผ่านเดิมใช้ได้

Release จะล้มเหลวหาก migration ใน checkout ไม่ตรงกับช่วง schema ใน manifest โดยเฉพาะเมื่อ release รุ่นใหม่มี migration เพิ่ม ให้อัปเดต checkout สำหรับเครื่องมือดูแลระบบก่อน การติดตั้งใหม่ด้วย GHCR ใช้ `sh deploy.sh --prepare` ตามด้วย `--scope all` หากใช้ package ส่วนตัว ให้เข้าสู่ GHCR บน VPS ด้วยบัญชีที่รัน Docker และ credential ที่อ่าน package ได้ ขั้นตอน dry run จะระบุ digest ที่ยังไม่อยู่ในเครื่องและยังไม่ตรวจสิทธิ์ดึงจริง

Dashboards ที่ใช้ SSH tunnel ให้คง `RIMWORLD_WEB_BIND=127.0.0.1` เป็นค่าเริ่มต้น หากต้องการให้เข้า `http://VPS_IP:10005` โดยเจตนา ให้ตั้งค่า `RIMWORLD_WEB_BIND=0.0.0.0` ใน `compose.env` จากนั้น deploy เฉพาะเว็บและจำกัด TCP 10005 ให้เปิดเฉพาะ IP ที่เชื่อถือได้ใน firewall ของผู้ให้บริการ HTTP แบบนี้ไม่เข้ารหัส สำหรับ HTTPS proxy ให้คง loopback bind ตั้ง `DASHBOARD_ORIGIN=https://<your-host>` และ `COOKIE_SECURE=true` ใน `web.env` แล้ว deploy เฉพาะเว็บ ใช้ origin เดียวกันกับที่ผู้ใช้เปิดจริง

Beekeeper เป็นเครื่องมือเสริม เข้าได้ทาง SSH tunnel โดยไม่ต้องมีการลงชื่อเข้าใช้หน้า GUI; PostgreSQL ตรวจ credential แยกกัน หากปิด ให้ตั้ง `RWT_BEEKEEPER_ENABLED=0` (ติดตั้งครั้งแรกตั้งค่าก่อน `sh deploy.sh` ได้) และหยุด container เดิมด้วย `docker compose --env-file .rwt-deploy/compose.env stop beekeeper` หากกำลังรันอยู่

## สำรองและกู้คืน

```sh
sh scripts/backup.sh --scope db
sh scripts/backup.sh --scope full --maintenance
sh scripts/verify-backup.sh
sh scripts/verify-backup.sh <BACKUP_ID>
```

Backup แบบ DB ใช้ PostgreSQL custom dump พร้อมสิทธิ์ของตาราง และไม่หยุดเกม Backup แบบ full หยุด API และเกมตามลำดับเพื่อไม่ให้บันทึกเซฟขณะอ่าน แล้วตรวจ archive ของ game data กับ bridge ก่อนเปิดบริการเดิมกลับขึ้นมา การเปลี่ยน image เกมจะปล่อยเกมไว้ในสถานะหยุดจนเริ่ม image ที่เลือก เก็บ world, saves, config, game logs/bridge ที่จำเป็น, environment และข้อมูล release ถ้ามี management request รออยู่ ให้รอให้เสร็จก่อนลองอีกครั้ง ไม่ย้ายคำสั่งพักไว้หรือ session เว็บไปยังระบบกู้คืน

ตำแหน่งเริ่มต้นคือ `.rwt-deploy/backups/<BACKUP_ID>/` ตั้ง `RWT_BACKUP_DIR` เป็น directory ส่วนตัวแยก disk ได้ Archive มีรหัสผ่านจริงจากไฟล์สภาพแวดล้อมและข้อมูลผู้เล่น เก็บสิทธิ์ระดับเจ้าของและคัดลอก **ทั้ง directory** ไปที่จัดเก็บนอก VPS ที่เข้ารหัสและจำกัดผู้เข้าถึง ค่าเริ่มต้นเก็บอย่างน้อย 3 รุ่นต่อประเภท ตั้งเพดานได้ด้วย `RWT_BACKUP_MAX_COUNT`, `RWT_BACKUP_MAX_DAYS`, `RWT_BACKUP_MIN_KEEP` ส่วน backup เดิมในเกมมีอายุและนโยบายแยกจาก snapshot นี้

```sh
sh scripts/restore.sh <BACKUP_ID> --new-project rwt-recovery \
  --game-port 35555 --web-port 11005 --confirm <BACKUP_ID> --start
```

ค่า `--confirm` ต้องตรง ID เดิม Restore สร้างโปรเจกต์ Docker, PostgreSQL volume และ game path ใหม่ภายใต้ `.rwt-deploy/recovery/<PROJECT>/` โดยไม่เขียนทับระบบเดิม เปิดกู้คืนบน loopback เท่านั้น; ตรวจ login, บัญชี, world ที่ถูกต้อง และเซฟกับเกมจริงก่อนสลับทราฟฟิก `--start` จะ build แอปจาก checkout ที่ใช้กู้คืนและรัน smoke tests; ถ้าต้องการ image รุ่นเดิม ให้ใช้ release digest ที่บันทึกใน `release.json` และใช้ deploy-release กับ `--state-dir` ของโปรเจกต์กู้คืน

ใช้ `--scope db` เพื่อกู้ฐานข้อมูลแยกไว้โดยไม่เริ่มเกม หรือ `--scope game` เพื่อแตกไฟล์เกมและ bridge ออกมาตรวจอย่างเดียว สำหรับ VPS เครื่องใหม่ให้รัน `sh deploy.sh --prepare` ก่อน ชี้ `RWT_BACKUP_DIR` ไปยังชุดที่คัดลอกมาแล้วใช้คำสั่ง Restore เหมือนข้างต้น กู้เฉพาะ backup จากแหล่งที่เชื่อถือได้ เพราะ checksum ตรวจความเสียหายของไฟล์ ไม่ได้ยืนยันผู้สร้าง archive

PostgreSQL ต้องใช้ major เดียวกับที่สำรอง เครื่องมือสร้าง roles ที่ repo ใช้คือ `rimworld_web` และ `rimworld_api` จาก environment เดิม รวมทั้ง owner จาก `postgres.env` แล้วให้ `pg_restore` คืน grants ของแอป หากสร้าง role อื่นเอง ให้เตรียม roles และสิทธิ์นั้นก่อน restore ในสภาพแวดล้อมแยก ถ้า restore ไม่สำเร็จ จะมีไฟล์ `restore-incomplete`; ตรวจสาเหตุและลองด้วยชื่อโปรเจกต์ใหม่ คำสั่งไม่ได้ตัดสินใจสลับระบบแทนผู้ดูแล

## Rollback และตรวจปัญหา

```sh
sh scripts/release-status.sh
sh scripts/rollback.sh --scope web
sh scripts/migrate.sh --status
sh scripts/smoke-test.sh
docker compose --env-file .rwt-deploy/compose.env logs --tail 100 web api rimworld
docker compose --env-file .rwt-deploy/compose.env restart --no-deps rimworld
docker compose --env-file .rwt-deploy/compose.env restart --no-deps web
```

Rollback ใช้ image รุ่นก่อนที่ผ่าน smoke และตรวจ schema ก่อนเสมอ ไม่ย้อน PostgreSQL หรือการแก้ `compose.env` หาก deploy ไม่ผ่าน จะลองคืน image เดิมเมื่อบันทึกรุ่นเดิมได้และยังเข้ากัน หาก image เดิมไม่มีบน VPS แล้ว ระบบจะดึงจาก GHCR ถ้าเป็น image ที่ build บนเครื่องให้รักษา tag `rwt-local/` ที่ใช้ย้อน การ rollback เกมต้องเพิ่ม `--maintenance`

- **Migration ล้มเหลว:** อ่านเวอร์ชันและ checksum ที่ผิดด้วย `scripts/migrate.sh --status` อย่าแก้ SQL ที่ถูก apply ไปแล้ว หากต้องแก้ schema ให้เพิ่ม migration ใหม่ Migration แบบ manual ทำ backup DB ก่อนและรันด้วย `sh scripts/migrate.sh`
- **DB ไม่พร้อม:** ตรวจ health และ log ของ PostgreSQL ชื่อ volume ต้องเดิม เก็บข้อมูลไว้แล้วตรวจ disk และ credentials ของ roles อย่าลบ volume เพื่อแก้ login
- **อัปเดต PostgreSQL 16.x เดิม:** จัด maintenance และรัน backup ก่อน แก้ `POSTGRES_VERSION` ให้ตรงกับ tag + digest ของ PostgreSQL 16 ที่ตรวจแล้ว (ค่าเริ่มต้นสำหรับเครื่องใหม่อยู่ใน `deploy.sh`) จากนั้นใช้ `docker compose --env-file .rwt-deploy/compose.env up -d --no-deps --wait postgres` และรัน smoke test เครื่องมือ deploy app จะไม่ recreate PostgreSQL เดิมให้อัตโนมัติ การอัปเกรดข้าม major ต้องวางแผนย้ายฐานข้อมูลแยก
- **Dashboard เข้าไม่ได้:** ตรวจ SSH tunnel, loopback bind, cookie/origin หลังเปิด HTTPS และสถานะ API
- **เกมเข้าไม่ได้:** ตรวจ listener และพอร์ตจากใน stack ด้วย smoke แล้วทดสอบ **จากเครื่องอื่น**: `python3 scripts/ops.py external <PUBLIC_IP> --port 25555` TCP timeout อาจมาจาก host firewall, cloud firewall, routing หรือ NAT; ผลอย่างเดียวแยกสาเหตุไม่ได้
- **ทดสอบผู้เล่นจริง:** ใช้ RimWorld พร้อมม็อดรุ่นเข้ากัน เชื่อมต่อจากนอก VPS สร้างหรือเข้าโลกเดิม เซฟ ออกจากเกม แล้วเข้าใหม่เพื่อดูว่าโหลดเซฟได้ นี่เป็นการทดสอบแยกจาก TCP smoke
- **พื้นที่เต็ม:** ตรวจที่เก็บ backup ก่อน deploy ย้าย backup ที่ตรวจแล้วไปพื้นที่อื่น ใช้นโยบาย retention กับ backup เท่านั้น อย่าล้าง Docker volumes
- **GHCR image หาย:** ตรวจ release SHA, package access และ digest ใน manifest ถ้าเอา image เดิมกลับไม่ได้ ให้หยุดและเลือก release ที่รองรับ schema ปัจจุบัน

ผล deploy ที่ผ่าน/ล้มเหลว เวอร์ชัน ระยะเวลาโดยเวลาเริ่มและจบ และ backup ID อยู่ใน `.rwt-deploy/deployments.jsonl` ส่วน `release-state.json` แสดง image และ release ที่ใช้งานล่าสุด แยกตามบริการ
