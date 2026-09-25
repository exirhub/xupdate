# XUPDATE

این پروژه مستقل است و نصب را از دیتابیس ارسالی خودت انجام می‌دهد. پروژهٔ `xrm-1` فقط برای شناخت روش نصب بررسی شده و در نصب این پروژه استفاده یا تغییر داده نمی‌شود.

ترنسپورت همان **gRPC Multi** است. عبارت XHTTP در نام نمایشی کانفیگ، نوع اتصال را تغییر نمی‌دهد.

## نصب از GitHub

همان دیتابیس ارسالی با نام `x-ui.db` در ریشهٔ مخزن قرار دارد و نصب‌کننده خودکار از آن استفاده می‌کند:

```bash
git clone https://github.com/exirhub/xupdate.git
cd xupdate
sudo bash install.sh
```

فایل `x-ui.db` بدون تغییر حتی یک بایت از فایل `57.128.162.236_2026-09-24_171935.db` کپی شده و طبق درخواست صریح مالک، با همان گواهی، کلید و اطلاعات موجود در مخزن قرار گرفته است. برای بررسی تطابق اجرا کن:

```bash
sha256sum -c x-ui.db.sha256
```

## نصب خودکار با Cloud-init و Startup Script

فایل آمادهٔ [`cloud-init/xupdate.yaml`](cloud-init/xupdate.yaml) را هنگام ساخت سرور در قسمت User Data یا Cloud config قرار بده. برای بخش‌هایی که اسکریپت Bash می‌خواهند و برای نصب مستقیم با SSH، فایل [`scripts/bootstrap.sh`](scripts/bootstrap.sh) آماده است:

```bash
curl -fL --retry 5 --connect-timeout 15 --max-time 180 \
  https://raw.githubusercontent.com/exirhub/xupdate/main/scripts/bootstrap.sh \
  -o /tmp/xupdate-bootstrap.sh && sudo bash /tmp/xupdate-bootstrap.sh
```

روش Hetzner، OVH/OpenStack، DigitalOcean، Vultr، Linode، AWS، Azure، Google Compute Engine و سرورهای دیگر در [راهنمای دیتاسنترها](cloud-init/README.fa.md) آمده است. اجرای دوباره نصب کامل‌شده را جایگزین نمی‌کند؛ حذف بدون پشتیبان فقط با `--clean-install` است. اسکریپت [`scripts/diagnose.sh`](scripts/diagnose.sh) نیز برای بررسی وضعیت، DNS، پورت‌ها و لاگ‌ها اضافه شده است.

## پیش‌نیازها و بسته‌های قبلی

بستهٔ نصب خصوصی که قبلاً دانلود کرده‌ای نیز همچنان با این دستورها قابل استفاده است:

```bash
tar -xzf XUPDATE-private-install.tar.gz
cd XUPDATE
sudo bash install.sh
```

سرور باید دارای Ubuntu 24.04 یا جدیدتر / Debian 12 یا جدیدتر، systemd و معماری amd64 یا arm64 باشد. دریافت بسته‌های سیستم و نسخهٔ مشخص 3x-ui به اینترنت نیاز دارد.

## حذف نصب قبلی و نصب جدید

اگر خطای وجود `/etc/x-ui` را می‌بینی، از داخل پوشهٔ پروژه اجرا کن:

```bash
git pull --ff-only
sudo bash install.sh --clean-install
```

این حالت نصب قبلی x-ui/XUPDATE، دیتابیس قبلی، فایل‌های سرویس، تنظیمات اختصاصی سرویس و لاگ‌های آن را از مسیرهای استاندارد حذف می‌کند و **پشتیبان نمی‌گیرد**. نصب جدید از همان `x-ui.db` داخل مخزن انجام می‌شود. اطلاعات نصب قبلی با دیتابیس همراه مخزن جایگزین می‌شوند.

دریافت و بررسی فایل‌ها پیش از حذف انجام می‌شود. اگر پورت لازم را برنامهٔ دیگری گرفته باشد، حذف فایل‌های قدیمی انجام نمی‌شود. سرویس Nginx مستقل و سایت‌های دیگر حذف نمی‌شوند. بعد از شروع حذف، شکست نصب باعث بازگرداندن پنل قبلی نخواهد شد. این حالت برای پوشهٔ باقی‌مانده از نصب قبلی هم کار می‌کند. فایل دیتابیس داخل مخزن تغییر نمی‌کند.

پس از نصب:

```bash
sudo cat /etc/xupdate/access.txt
sudo xupdate doctor
sudo xupdate doctor --public
```

آدرس ورود پنل از همان مسیر ذخیره‌شده در دیتابیس ساخته می‌شود. نام کاربری، رمز پنل، UUID کلاینت‌ها، شناسه‌های اشتراک، محدودیت‌ها و مصرف ثبت‌شده حفظ می‌شوند.

## خطای DNS هنگام دریافت بسته‌ها

خطای `Temporary failure resolving` برای مخزن‌های اوبونتو یعنی سرور نتوانسته نام مخزن را به IP تبدیل کند. اگر نصب در همین مرحلهٔ APT متوقف شود، حذف x-ui قبلی هنوز شروع نشده است. گزینهٔ `--fix-missing` مشکل DNS را حل نمی‌کند.

نصب‌کننده اکنون با `apt-get --error-on=any update` در صورت خطای دریافت فهرست بسته‌ها متوقف می‌شود و با فهرست قدیمی ادامه نمی‌دهد. تنظیم DNS سرور را خودکار تغییر نمی‌دهد.

روی Ubuntu دارای `systemd-resolved`، برای تنظیم موقت DNS این بلوک را اجرا کن. باید مسیر IPv4 و دسترسی به DNSهای انتخاب‌شده برقرار باشد:

```bash
(
    set -euo pipefail
    command -v resolvectl >/dev/null
    sudo systemctl restart systemd-resolved
    xupdate_iface=$(ip -4 route get 1.1.1.1 | awk '{for (i=1; i<NF; i++) if ($i == "dev") {print $(i+1); exit}}')
    test -n "$xupdate_iface"
    sudo resolvectl dns "$xupdate_iface" 1.1.1.1 8.8.8.8
    sudo resolvectl domain "$xupdate_iface" '~.'
    sudo resolvectl flush-caches
    for xupdate_host in nova.clouds.archive.ubuntu.com security.ubuntu.com github.com; do
        timeout 20 getent ahosts "$xupdate_host" || {
            echo "DNS lookup still failed: $xupdate_host" >&2
            exit 1
        }
    done
)
```

اگر بررسی هر سه نام موفق بود، از پوشهٔ پروژه اجرا کن:

```bash
git pull --ff-only
sudo bash install.sh --clean-install
```

این تنظیم DNS موقت است و ممکن است با راه‌اندازی مجدد یا تغییر تنظیمات شبکه از بین برود. فایل `/etc/resolv.conf` بازنویسی نمی‌شود. اگر `resolvectl` وجود نداشت یا خطا ادامه داشت، خروجی این دستورها برای تشخیص علت لازم است:

```bash
ip -4 route
readlink -f /etc/resolv.conf
cat /etc/resolv.conf
systemctl --no-pager --full status systemd-resolved
resolvectl --no-pager status
```

پس از تشخیص علت، DNS دائمی باید از طریق مدیر شبکهٔ موجود سرور تنظیم شود. تنظیم ناموفق resolver یا محدودیت خروجی شبکه نیز می‌تواند باعث این خطا شود.

## تغییر دقیق تنظیمات

فایل ورودی دست نمی‌خورد؛ تغییرات فقط روی کپی اجرایی انجام می‌شود. Nginx با همان گواهی و کلید روی پورت 443 قرار می‌گیرد، سایت را نمایش می‌دهد و مسیر `google.internal.analytics.v1.Tracker` را به همان ورودی gRPC روی `127.0.0.1:10001` می‌فرستد. TLS در Nginx پایان می‌یابد و ارتباط داخلی روی loopback است. اطلاعات Host در پنل باعث می‌شود لینک‌های خروجی همچنان TLS، پورت 443، SNI دامنهٔ `exirhub.site` و آدرس عمومی `188.114.97.6` داشته باشند.

دسترسی پنل و اشتراک نیز از طریق HTTPS و مسیرهای موجود انجام می‌شود؛ پورت‌های داخلی فقط روی loopback گوش می‌دهند. هیچ ورودی XHTTP، حساب جایگزین یا کلید جدید ساخته نمی‌شود.

رکورد نارنجی Cloudflare برای `exirhub.site` باید به IP سرور جدید اشاره کند؛ `188.114.97.6` آدرس لبهٔ Cloudflare در کانفیگ کلاینت است، نه IP سرور جدید. تنظیم gRPC و Full (strict) باید برقرار باشد. نصب‌کننده DNS یا فایروال را تغییر نمی‌دهد.

## بررسی و بازگشت

پیش‌نمایش بدون نصب:

```bash
bash install.sh --dry-run --output /root/xupdate-preview
```

پاک‌کردن نصب جدید؛ اگر با `--clean-install` نصب کرده‌ای، این دستور نیز پشتیبان نمی‌گیرد:

```bash
sudo xupdate rollback
```

نسخهٔ فعلی GitHub دیتابیس را همراه دارد. آرشیو قدیمی `XUPDATE-source.tar.gz` پیش از این تغییر ساخته شده و برای نصب از آن باید مسیر دیتابیس را با `--db` مشخص کنی. برای استفاده از دیتابیس دیگری در نسخهٔ فعلی نیز همین گزینه وجود دارد.

تست‌های دیتابیس، ساخت CSS و بررسی نحوی کدها انجام شده‌اند. بررسی ظاهری در مرورگر کامل نشده است؛ نصب واقعی systemd، تست Nginx و Xray و اتصال کامل کلاینت باید روی سرور مقصد انجام شوند. جزئیات در `VALIDATION.md` و راهنمای فنی در `README.md` آمده است. این معماری ادعای نامرئی‌شدن مطلق در برابر DPI یا Cloudflare ندارد.
