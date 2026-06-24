Databento Gold Flow - Mobile HTML
=================================

الغرض:
منصة صغيرة تفتح من الهاتف وتقرأ Databento Live API للذهب GC Futures عبر GLBX.MDP3 ثم تعرض:
- آخر سعر GC
- ضغط شراء/بيع Buy/Sell aggressor
- Delta
- Volume
- Big Trades
- تحذير Absorption إذا السعر لا يتحرك مع الدلتا

مهم جداً:
لا تضع Databento API key داخل index.html أبداً.
ضعه في Vercel Environment Variables باسم:
DATABENTO_API_KEY

طريقة التشغيل على Vercel:
1) ارفع الملفات كما هي إلى GitHub.
2) اعمل Import للمشروع في Vercel.
3) من Vercel > Project > Settings > Environment Variables:
   Name: DATABENTO_API_KEY
   Value: مفتاح Databento الخاص بك
4) اضغط Redeploy.
5) افتح رابط Vercel من الهاتف.
6) اضغط "فحص الآن".

الإعداد الافتراضي:
Symbol = GC.FUT
stype = parent
seconds = 8

إذا ظهر NO DATA:
- جرّب seconds = 15.
- تأكد أن السوق مفتوح.
- تأكد أن حسابك فيه Live entitlement لـ GLBX.MDP3.
- إذا لديك رمز عقد محدد مثل GCM6 يمكنك وضعه واختيار raw_symbol.

ملاحظة للتداول:
هذه ليست منصة تنفيذ صفقات ولا تعطي أمر دخول مضمون.
استعملها كرادار تأكيد فقط بجانب XAUUSD على MT5/TradingView.
