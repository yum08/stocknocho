"""Quick check of end-to-end pipeline output."""
import requests, json

print("\n" + "="*70)
print("  STOCKRAG - END-TO-END PIPELINE OUTPUT")
print("="*70)

# Pipeline status
ps = requests.get('http://localhost:5000/api/pipeline/status').json()
stages = ps['stages']
print("\nPipeline Status:")
for k, s in stages.items():
    status = "DONE" if s['pending'] == 0 and s['done'] > 0 else f"{s['pending']} PENDING" if s['pending'] > 0 else "EMPTY"
    print(f"  {s['label']:25s}  {s['done']:4d} done  |  {status}")

# Stocks with signals
print("\n" + "-"*70)
print("  STOCK SIGNALS (Final Output)")
print("-"*70)

stocks = requests.get('http://localhost:5000/api/stocks').json()['stocks']
found = 0
for s in stocks:
    sig_r = requests.get(f"http://localhost:5000/api/stocks/{s['id']}/signal").json()
    ment_r = requests.get(f"http://localhost:5000/api/stocks/{s['id']}/mentions?hours=720&limit=10").json()
    
    has_signal = sig_r.get('signal') is not None
    has_mentions = ment_r.get('count', 0) > 0
    
    if has_signal or has_mentions:
        found += 1
        sig = sig_r.get('signal', {})
        print(f"\n  [{s['symbol']}] {s['name']} ({s.get('sector','-')})")
        if has_signal:
            print(f"    Signal:    {sig.get('signal_strength', '-')}")
            print(f"    Direction: {sig.get('predicted_direction', '-')}")
            print(f"    Sentiment: {sig.get('avg_sentiment', '-')} (confidence: {sig.get('confidence', '-')})")
            print(f"    Mentions:  {sig.get('total_mentions',0)} total  "
                  f"(Bull:{sig.get('bullish_count',0)} Bear:{sig.get('bearish_count',0)} Neutral:{sig.get('neutral_count',0)})")
        
        if has_mentions:
            print(f"    Recent mentions ({ment_r['count']}):")
            for m in ment_r.get('mentions', [])[:3]:
                sent = m.get('sentiment_label', '?')
                score = m.get('sentiment_score')
                score_str = f"({score:.2f})" if score is not None else ""
                print(f"      - '{m.get('matched_text','')[:40]}' "
                      f"| {sent} {score_str} "
                      f"| action={m.get('action_suggested','-')} "
                      f"| target={m.get('target_price','-')} SL={m.get('stop_loss','-')}")

if found == 0:
    print("\n  No stocks with signals or mentions found.")
else:
    print(f"\n  Total: {found} stock(s) with data")

# Semantic search test
print("\n" + "-"*70)
print("  SEMANTIC SEARCH TEST")
print("-"*70)
sr = requests.get('http://localhost:5000/api/search?q=stock+market&n=3').json()
if sr.get('results'):
    for i, r in enumerate(sr['results'][:3]):
        txt = (r.get('text','') or '')[:80]
        print(f"  #{i+1} [{r.get('metadata',{}).get('platform','')}] {txt}")
else:
    print("  No search results (vectors may not be synced)")

print("\n" + "="*70)
print("  DONE - Visit http://localhost:5000 in browser")
print("="*70 + "\n")
