# -*- coding: utf-8 -*-
"""评分测谎仪(scoring harness):任何评分器的分数 → 自动与真人分对比,输出可信度报告。
用法:把 {剧名: 分数} 传进 validate()，得到 Spearman、头部是否进top、0分是否进bottom、排序对照。
这是"防自欺"的核心工具:任何评分器(人写的/Codex做的/LLM的)都必须先过这台仪器。
"""
import json, statistics as st

def load_human():
    ds=json.load(open('data/benchmark/human_scoring/human_scoring_dataset.json'))
    hum={}
    for dr in ds.get('data',[]):
        t=dr.get('drama_folder') or dr.get('source_file') or ''
        bs=[e.get('benchmark_total') for e in dr.get('episodes_scored',[]) if isinstance(e.get('benchmark_total'),(int,float))]
        if bs: hum[t]=sum(bs)/len(bs)
    return hum

def spearman(xs,ys):
    n=len(xs)
    if n<3: return float('nan')
    def rank(v):
        s=sorted(range(len(v)),key=lambda i:v[i]); r=[0.0]*len(v)
        # 处理并列：平均秩
        i=0
        while i<len(s):
            j=i
            while j+1<len(s) and v[s[j+1]]==v[s[i]]: j+=1
            avg=sum(range(i,j+1))/(j-i+1)
            for k in range(i,j+1): r[s[k]]=avg
            i=j+1
        return r
    rx,ry=rank(xs),rank(ys)
    mx,my=st.mean(rx),st.mean(ry)
    cov=sum((rx[i]-mx)*(ry[i]-my) for i in range(n))
    sx=(sum((rx[i]-mx)**2 for i in range(n)))**.5
    sy=(sum((ry[i]-my)**2 for i in range(n)))**.5
    return cov/(sx*sy) if sx*sy else float('nan')

def validate(scores: dict, label="评分器"):
    """scores: {剧名(可部分匹配): 分数}"""
    hum=load_human()
    pairs=[]
    for name,sc in scores.items():
        h=next((v for kk,v in hum.items() if kk[:6] in name or name[:6] in kk), None)
        if h is not None: pairs.append((name[:18],sc,h))
    if len(pairs)<3:
        print(f"[{label}] 可对照样本不足({len(pairs)})"); return
    S=[p[1] for p in pairs]; H=[p[2] for p in pairs]
    r=spearman(S,H)
    # 头部(真人≥80)是否在评分器top1/3；垫底(真人≤10)是否在bottom1/3
    order=sorted(range(len(pairs)), key=lambda i:-S[i])
    n=len(pairs); topk=set(order[:max(1,n//3)]); botk=set(order[-max(1,n//3):])
    head_ok=all(i in topk for i in range(len(pairs)) if H[i]>=80)
    zero_ok=all(i in botk for i in range(len(pairs)) if H[i]<=10)
    print(f"\n=== [{label}] 测谎报告 (n={n}) ===")
    print(f"  Spearman(与真人) = {r:+.2f}   {'✅达标(≥0.6)' if r>=0.6 else '❌未达标(<0.6)'}")
    print(f"  头部剧(真人≥80)是否都进评分器top1/3: {'✅' if head_ok else '❌'}")
    print(f"  垫底剧(真人≤10)是否都进bottom1/3: {'✅' if zero_ok else '❌'}")
    print("  排序对照(评分器从高到低):")
    for i in order:
        print(f"    {pairs[i][0]:18} 评分器{S[i]:+.2f} | 真人{H[i]:.0f}")
    return r
