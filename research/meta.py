import json, urllib.request, sys, concurrent.futures as cf
UA={"User-Agent":"Mozilla/5.0"}
def get(u, js=True):
    r=urllib.request.Request(u,headers=UA)
    with urllib.request.urlopen(r,timeout=60) as f:
        b=f.read()
    return json.loads(b) if js else b.decode('utf-8','replace')

def one(mid):
    out={"id":mid}
    try:
        d=get(f"https://huggingface.co/api/models/{mid}")
    except Exception as e:
        return {"id":mid,"error":str(e)}
    cd=d.get("cardData") or {}
    out["license"]=cd.get("license") or cd.get("license_name")
    out["lic_link"]=cd.get("license_link")
    out["base_model"]=cd.get("base_model")
    out["library"]=d.get("library_name")
    st=d.get("safetensors") or {}
    out["params_total"]=st.get("total")
    out["params_dtype"]=list((st.get("parameters") or {}).keys())
    out["downloads"]=d.get("downloads"); out["likes"]=d.get("likes")
    out["created"]=(d.get("createdAt") or "")[:10]
    out["pipeline"]=d.get("pipeline_tag")
    cfg=d.get("config") or {}
    out["architectures"]=cfg.get("architectures")
    out["model_type"]=cfg.get("model_type")
    out["gated"]=d.get("gated")
    try:
        c=json.loads(get(f"https://huggingface.co/{mid}/raw/main/config.json", js=False))
        for k in ["num_hidden_layers","num_attention_heads","num_key_value_heads","head_dim",
                  "hidden_size","max_position_embeddings","vocab_size","tie_word_embeddings",
                  "num_experts","num_local_experts","num_experts_per_tok","n_routed_experts",
                  "moe_intermediate_size","intermediate_size","sliding_window","torch_dtype",
                  "num_key_value_heads","quantization_config","rope_scaling","layer_types"]:
            if k in c: out["cfg_"+k]=c[k]
        for k,v in c.items():
            if "expert" in k.lower() and ("cfg_"+k) not in out: out["cfg_"+k]=v
    except Exception as e:
        out["cfg_error"]=str(e)[:80]
    return out

ids=[l.strip() for l in open(sys.argv[1]) if l.strip() and not l.startswith("#")]
res=[]
with cf.ThreadPoolExecutor(10) as ex:
    for r in ex.map(one, ids): res.append(r)
json.dump(res, open(sys.argv[2],"w"), ensure_ascii=False, indent=1)
for r in res:
    if r.get("error"): print(f"{r['id']:<55} ERROR {r['error'][:60]}"); continue
    p=r.get("params_total")
    p=f"{p/1e9:.1f}B" if p else "?"
    print(f"{r['id']:<55} {p:>8} lic={str(r.get('license')):<14} arch={str(r.get('architectures'))[:38]:<38} L={r.get('cfg_num_hidden_layers')} kv={r.get('cfg_num_key_value_heads')} hd={r.get('cfg_head_dim')} ctx={r.get('cfg_max_position_embeddings')} E={r.get('cfg_num_experts') or r.get('cfg_n_routed_experts')} E/tok={r.get('cfg_num_experts_per_tok')} moe={r.get('cfg_moe_intermediate_size')} tie={r.get('cfg_tie_word_embeddings')}")
