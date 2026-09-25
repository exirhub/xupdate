# نصب خودکار روی دیتاسنترها

همهٔ روش‌ها از همان دیتابیس `x-ui.db` داخل مخزن، همان گواهی و همان اتصال **VLESS/gRPC Multi** استفاده می‌کنند. سیستم‌عامل باید **Ubuntu 24.04 یا جدیدتر / Debian 12 یا جدیدتر**، معماری **amd64 یا arm64** و دارای systemd باشد.

## فایل مناسب را انتخاب کن

| کاربرد | فایل |
| --- | --- |
| نصب خودکار هنگام ساخت سرور با Cloud-init | [`xupdate.yaml`](xupdate.yaml) |
| فیلد Bash Startup Script یا اجرای مستقیم با SSH | [`scripts/bootstrap.sh`](../scripts/bootstrap.sh) |
| بررسی وضعیت نصب، DNS، پورت‌ها و لاگ‌ها | [`scripts/diagnose.sh`](../scripts/diagnose.sh) |

فایل YAML کامل است و نیاز به نوشتن IP، نام کارت شبکه، رمز یا کلید جدید ندارد. کل فایل، همراه خط اول `#cloud-config`، باید در فیلد مربوط قرار بگیرد. تنظیم شبکه و دسترسی SSH طبق ایمیج و انتخاب‌های خود دیتاسنتر انجام می‌شود.

## محل استفاده در هر دیتاسنتر

| دیتاسنتر / محصول | روش |
| --- | --- |
| Hetzner Cloud | هنگام ساخت سرور، بخش **Cloud config** ← محتوای `xupdate.yaml` |
| OVH Public Cloud / OpenStack | User Data هنگام ساخت Instance؛ گزینهٔ `--user-data` در OpenStack نیز قابل استفاده است ← `xupdate.yaml` |
| DigitalOcean | **Additional Options → Startup scripts** ← `xupdate.yaml` |
| Vultr Cloud Compute | **Enable Cloud-Init User-Data** ← `xupdate.yaml` |
| Akamai / Linode | **Add user data** برای ایمیج و منطقهٔ سازگار با Metadata ← `xupdate.yaml`؛ در مسیر StackScript از فایل Bash استفاده کن |
| AWS EC2 | **Advanced details → User data** روی ایمیج Ubuntu/Debian ← `xupdate.yaml`؛ گزینهٔ already base64 encoded خاموش باشد |
| Azure | **Custom data** روی ایمیج Ubuntu/Debian دارای cloud-init ← `xupdate.yaml` |
| Google Compute Engine | **Startup script** یا کلید `startup-script` ← محتوای `bootstrap.sh`؛ این فیلد فایل Bash می‌خواهد |
| RamNode، OVH VPS/Dedicated، Contabo، Netcup و سایر سرورها | پس از نصب سیستم‌عامل سازگار، دستور SSH زیر؛ Cloud-init فقط وقتی محصول و ایمیج انتخاب‌شده آن را پشتیبانی می‌کنند |

این جدول بر اساس روش‌های مستند ارائه‌دهندگان است؛ نصب زنده در تک‌تک دیتاسنترها آزمایش نشده است. انتخاب پلن، منطقه، SSH Key و فایروال طبق اکانت خودت انجام می‌شود. برای AWS از Amazon Linux و برای سایر ارائه‌دهندگان از ایمیج‌های خارج از Ubuntu/Debian استفاده نکن.

## دستور نصب مستقیم

اگر curl نصب نیست، ابتدا بسته‌های `ca-certificates` و `curl` را با APT نصب کن. سپس:

```bash
curl -fL --retry 5 --connect-timeout 15 --max-time 180 \
  https://raw.githubusercontent.com/exirhub/xupdate/main/scripts/bootstrap.sh \
  -o /tmp/xupdate-bootstrap.sh && sudo bash /tmp/xupdate-bootstrap.sh
```

یا از پوشهٔ کلون‌شدهٔ پروژه:

```bash
sudo bash scripts/bootstrap.sh
```

اسکریپت پیش‌نیازها را نصب می‌کند، سورس را با تلاش مجدد دریافت می‌کند، هش دیتابیس را بررسی می‌کند و نصب‌کنندهٔ اصلی را اجرا می‌کند. نسخهٔ 3x-ui طبق فایل قفل پروژه ثابت است. خطای APT، دریافت سورس یا هش، اجرای نصب را متوقف می‌کند.

اگر XUPDATE از قبل نصب شده باشد، اجرای دوباره از آن عبور می‌کند و دیتابیس اجرایی را جایگزین نمی‌کند. این پیام به معنی تأیید سلامت فعلی Xray نیست؛ سلامت با `xupdate doctor` بررسی می‌شود.

برای **حذف کامل نصب قبلی و نصب مجدد بدون پشتیبان**، فقط وقتی خودت قصد جایگزینی داری، دستی اجرا کن:

```bash
sudo bash scripts/bootstrap.sh --clean-install
```

این گزینه را داخل Startup Script تکرارشونده قرار نده؛ مثلاً اسکریپت راه‌اندازی Google Compute Engine ممکن است در بوت‌های بعدی هم اجرا شود. حالت پیش‌فرض برای اجرای مجدد مناسب است. این اسکریپت نصب است و برای آپدیت دیتابیس یا کد یک نصب فعال استفاده نمی‌شود.

## مشاهدهٔ نتیجه

روی سروری که با Cloud-init ساخته‌ای، پس از ورود با SSH:

```bash
sudo cloud-init status --wait --long
sudo tail -n 80 /var/log/xupdate-bootstrap.log
sudo xupdate doctor
sudo cat /etc/xupdate/access.txt
```

دستور `cloud-init status --wait` را داخل خود User Data قرار نده؛ آنجا منتظر تمام‌شدن خودش می‌ماند. اگر نصب شکست خورد، علت را در لاگ رفع کن و دستور نصب مستقیم را دوباره اجرا کن؛ نیازی به پاک‌کردن وضعیت cloud-init نیست.

برای بررسی کامل‌تر از پوشهٔ پروژه:

```bash
sudo bash scripts/diagnose.sh
```

این دستور فقط وضعیت را می‌خواند: سرویس‌ها، پورت‌ها، DNS، دسترسی کاربر `_apt` به فایل resolver و لاگ‌ها. تنظیمی را خودکار تغییر نمی‌دهد.

## شبکه و Cloudflare

TCP `443` باید از Cloudflare به سرور برسد. پورت `80` برای ریدایرکت HTTP اختیاری است. دسترسی SSH طبق تنظیم خودت باقی می‌ماند. پورت‌های `10001`، `8144` و `2096` داخلی هستند. DNS و دسترسی خروجی به مخزن‌های APT، GitHub و فایل‌های Release نیز لازم است.

فایروال دیتاسنتر و فایروال داخل سیستم‌عامل را متناسب با این پورت‌ها تنظیم کن. این فایل‌ها تنظیم DNS، Netplan، کارت شبکه، SSH یا فایروال را بازنویسی نمی‌کنند. سرور فقط دارای شبکهٔ خصوصی، بدون مسیر عمومی مناسب، از Cloudflare قابل دسترسی نمی‌شود.

رکورد نارنجی `exirhub.site` را به **IP مبدأ سرور جدید** متصل کن، gRPC را فعال کن و SSL را روی **Full (strict)** بگذار. آدرس `188.114.97.6` در کانفیگ، IP لبهٔ Cloudflare است. نصب چند سرور با این فایل به‌تنهایی برای آن‌ها DNS یا توزیع بار تنظیم نمی‌کند.

سپس:

```bash
sudo xupdate doctor --public
```

اتصال واقعی را نیز با همان کلاینت VLESS/gRPC امتحان کن؛ تست وب‌سایت به‌تنهایی موفقیت ترافیک VPN را ثابت نمی‌کند.

## انتخاب نسخهٔ سورس

پیش‌فرض شاخهٔ `main` است. برای استفاده از کامیت مشخصِ پوشهٔ کلون‌شده:

```bash
sudo bash scripts/bootstrap.sh --ref "$(git rev-parse HEAD)"
```

در فایل YAML نیز می‌توانی آخرین مقدار `main` در `runcmd` را با SHA کامل کامیت جایگزین کنی. برای ثابت‌ماندن کل فرایند، خود فایل Bootstrap/YAML را نیز از همان کامیت دریافت کن. کامیت آخرین نصب موفق در `/var/lib/xupdate-bootstrap/source-commit.txt` ثبت می‌شود.

جزئیات فنی، محدودیت‌ها و لینک مستندات رسمی ارائه‌دهندگان در [راهنمای انگلیسی](README.md) آمده است.
