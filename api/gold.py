import json
import os
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs


def _json(handler, status, payload):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _safe_str(x):
    if x is None:
        return ""
    if isinstance(x, bytes):
        return x.decode("utf-8", "ignore")
    # Handles enums such as Side.BID that stringify as "B" in some versions.
    if hasattr(x, "value"):
        try:
            return str(x.value)
        except Exception:
            pass
    return str(x).replace("'", "").replace('"', "")


def _price(x):
    if x is None:
        return None
    try:
        v = float(x)
        # Databento raw live prices can be fixed decimal integers where 1 = 1e-9.
        if abs(v) > 1_000_000:
            return v / 1_000_000_000.0
        return v
    except Exception:
        return None


def _ts_to_iso(ns_or_dt):
    try:
        if isinstance(ns_or_dt, int):
            return datetime.fromtimestamp(ns_or_dt / 1_000_000_000, tz=timezone.utc).strftime("%H:%M:%S")
        return str(ns_or_dt)
    except Exception:
        return ""


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        started = time.time()
        qs = parse_qs(urlparse(self.path).query)
        symbol = (qs.get("symbol", ["GC.FUT"])[0] or "GC.FUT").strip()
        stype = (qs.get("stype", ["parent"])[0] or "parent").strip()
        try:
            seconds = int(qs.get("seconds", ["8"])[0])
        except Exception:
            seconds = 8
        seconds = max(3, min(seconds, 15))

        api_key = os.getenv("DATABENTO_API_KEY")
        if not api_key:
            return _json(self, 500, {
                "ok": False,
                "error": "DATABENTO_API_KEY غير موجود في Vercel Environment Variables.",
                "fix": "Vercel > Project > Settings > Environment Variables > Add DATABENTO_API_KEY ثم Redeploy."
            })

        try:
            import databento as db
        except Exception as e:
            return _json(self, 500, {
                "ok": False,
                "error": "لم يتم تثبيت مكتبة databento على السيرفر.",
                "details": str(e),
                "fix": "تأكد أن ملف requirements.txt موجود وفيه databento ثم أعد Deploy."
            })

        trades = []
        system_msgs = []
        errors = []

        def on_record(record):
            try:
                rtype = record.__class__.__name__
                if "Error" in rtype:
                    errors.append(str(record))
                    return
                if "System" in rtype or "Symbol" in rtype:
                    system_msgs.append(str(record))
                    return

                action = _safe_str(getattr(record, "action", ""))
                size = int(getattr(record, "size", 0) or 0)
                px = _price(getattr(record, "price", None))
                side_raw = _safe_str(getattr(record, "side", "N")).upper()
                side_char = side_raw[-1:] if side_raw else "N"

                # Databento docs: B = bid/buy aggressor, A = ask/sell aggressor for trades.
                side = "BUY" if side_char == "B" else "SELL" if side_char == "A" else "NONE"
                if px is None or size <= 0:
                    return

                ts = getattr(record, "ts_event", None) or getattr(record, "ts_recv", None)
                trades.append({
                    "time": _ts_to_iso(ts),
                    "instrument_id": str(getattr(record, "instrument_id", "")),
                    "side": side,
                    "side_raw": side_raw,
                    "price": px,
                    "size": size,
                    "action": action,
                    "sequence": str(getattr(record, "sequence", "")),
                })
            except Exception as e:
                errors.append(f"callback parse error: {e}")

        client = None
        try:
            client = db.Live(key=api_key)
            client.subscribe(
                dataset="GLBX.MDP3",
                schema="trades",
                stype_in=stype,
                symbols=symbol,
            )
            client.add_callback(on_record)
            client.start()
            client.block_for_close(timeout=seconds)
        except Exception as e:
            try:
                if client:
                    client.stop()
            except Exception:
                pass
            return _json(self, 500, {
                "ok": False,
                "error": "فشل اتصال Databento Live أو لا توجد صلاحية Live/GLBX.MDP3.",
                "details": str(e),
                "symbol": symbol,
                "stype": stype,
                "hint": "جرّب GC.FUT مع stype=parent. إذا ظهرت 403 فالمشكلة Entitlement/permission. إذا لا توجد صفقات قد يكون السوق هادئاً أو مغلقاً."
            })
        finally:
            try:
                if client:
                    client.stop()
            except Exception:
                pass

        if not trades:
            return _json(self, 200, {
                "ok": True,
                "verdict": "NO DATA",
                "note": "الاتصال تم لكن لم تصل صفقات خلال مدة الفحص. جرّب 15 ثانية أو تأكد أن لديك Live entitlement لـ GLBX.MDP3 وأن السوق مفتوح.",
                "symbol": symbol,
                "stype": stype,
                "trade_count": 0,
                "system": system_msgs[-5:],
                "errors": errors[-5:],
                "latency_ms": round((time.time() - started) * 1000)
            })

        buy_qty = sum(t["size"] for t in trades if t["side"] == "BUY")
        sell_qty = sum(t["size"] for t in trades if t["side"] == "SELL")
        volume = sum(t["size"] for t in trades)
        delta = buy_qty - sell_qty
        pressure_pct = (delta / volume * 100.0) if volume else 0.0
        first_price = trades[0]["price"]
        last_price = trades[-1]["price"]
        price_change = last_price - first_price

        per_inst = {}
        for t in trades:
            k = t["instrument_id"] or "unknown"
            if k not in per_inst:
                per_inst[k] = {"instrument_id": k, "volume": 0, "delta": 0, "trades": 0}
            per_inst[k]["volume"] += t["size"]
            per_inst[k]["trades"] += 1
            per_inst[k]["delta"] += t["size"] if t["side"] == "BUY" else -t["size"] if t["side"] == "SELL" else 0
        top_instruments = sorted(per_inst.values(), key=lambda x: x["volume"], reverse=True)[:5]

        # Simple trading-confirmation logic, not an auto-trading signal.
        verdict = "WAIT"
        note = "استعملها كتأكيد فقط مع شارت XAUUSD/VWAP/support/resistance."
        if volume >= 1:
            if delta > 0 and price_change >= 0:
                verdict = "BUY PRESSURE"
                note = "ضغط شراء مؤكد نسبياً: مناسب فقط إذا شارت XAUUSD أيضاً فوق VWAP أو يكسر مقاومة."
            elif delta < 0 and price_change <= 0:
                verdict = "SELL PRESSURE"
                note = "ضغط بيع مؤكد نسبياً: مناسب فقط إذا XAUUSD أيضاً تحت VWAP أو يكسر دعم."
            elif delta > 0 and price_change < 0:
                verdict = "BUY ABSORPTION"
                note = "شراء موجود لكن السعر لا يصعد؛ قد يكون امتصاص عند مقاومة، تجنب شراء عشوائي."
            elif delta < 0 and price_change > 0:
                verdict = "SELL ABSORPTION"
                note = "بيع موجود لكن السعر لا ينزل؛ قد يكون امتصاص عند دعم، تجنب بيع عشوائي."

        big = [t for t in trades if t["size"] >= 5]

        return _json(self, 200, {
            "ok": True,
            "source": "Databento Live API / GLBX.MDP3 / trades",
            "symbol": symbol,
            "stype": stype,
            "window_seconds": seconds,
            "verdict": verdict,
            "note": note,
            "first_price": round(first_price, 4),
            "last_price": round(last_price, 4),
            "price_change": round(price_change, 4),
            "trade_count": len(trades),
            "volume": volume,
            "buy_qty": buy_qty,
            "sell_qty": sell_qty,
            "delta": delta,
            "pressure_pct": round(pressure_pct, 2),
            "top_instruments": top_instruments,
            "big_trades": big[-25:],
            "sample_trades": trades[-25:],
            "system": system_msgs[-5:],
            "errors": errors[-5:],
            "latency_ms": round((time.time() - started) * 1000),
            "server_utc": datetime.now(timezone.utc).isoformat()
        })
