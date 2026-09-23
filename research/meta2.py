import json, urllib.request, sys, concurrent.futures as cf
UA={"User-Agent":"Mozilla/5.0"}
def get(u, js=True):
    r=urllib.request.Request(u,headers=UA)
    with urllib.request.urlopen(r,timeout=60) as f: b=f.read()
    return json.loads(b) if js else b.decode('utf-8','replace')

KEYS=["num_hidden_layers","num_attention_heads","num_key_value_heads","head_dim","hidden_size",
 "max_position_embeddings","vocab_size","tie_word_embeddings","num_experts","num_local_experts",
 "num_experts_per_tok","n_routed_experts","moe_intermediate_size","intermediate_size","sliding_window",
 "torch_dtype","kv_lora_rank","qk_nope_head_dim","qk_rope_head_dim","v_head_dim","first_k_dense_replace",
 "n_shared_experts","rope_scaling","layer_types","full_attention_interval","linear_attn_config",
 "n_group","topk_group","norm_topk_prob","attention_bias","num_experts_per_token","shared_expert_intermediate_size"]

def flat(cfg, prefix=""):
    out={}
    for k,v in cfg.items():
        if isinstance(v,dict) and k in ("text_config","llm_config","language_config","transformer"):
            out.update(flat(v, prefix))
        elif k in KEYS or k in ("quantization_config",):
            if isinstance(v,(str,int,float,bool)) or (isinstance(v,list) and len(str(v))<200) or isinstance(v,dict) and k=="quantization_config":
                out[k]=v
    return out

def one(mid):
    out={"id":mid}
    try:
        d=get(f"https://huggingface.co/api/models/{mid}")
    except Exception as e: return {"id":mid,"error":str(e)[:80]}
    cd=d.get("cardData") or {}
    out["license"]=cd.get("license") or cd.get("license_name")
    out["lic_name"]=cd.get("license_name"); out["base"]=cd.get("base_model")
    st=d.get("safetensors") or {}
    out["params_total"]=st.get("total"); out["dt"]=list((st.get("parameters") or {}).keys())
    out["dl"]=d.get("downloads"); out["likes"]=d.get("likes"); out["created"]=(d.get("createdAt") or "")[:10]
    out["gated"]=d.get("gated"); out["pipeline"]=d.get("pipeline_tag")
    cfg=d.get("config") or {}
    out["arch"]=cfg.get("architectures"); out["mtype"]=cfg.get("model_type")
    try:
        c=json.loads(get(f"https://huggingface.co/{mid}/raw/main/config.json", js=False))
        out.update({("c_"+k):v for k,v in flat(c).items()})
    except Exception as e: out["cfgerr"]=str(e)[:60]
    return out

ids=[l.strip() for l in open(sys.argv[1]) if l.strip() and not l.startswith("#")]
res=[]
with cf.ThreadPoolExecutor(8) as ex:
    for r in ex.map(one, ids): res.append(r)
json.dump(res, open(sys.argv[2],"w"), ensure_ascii=False, indent=1)
def L(r,k):
    v=r.get("c_"+k)
    if isinstance(v,list): v=f"list[{len(v)}]"
    if isinstance(v,dict): v="{...}"
    return v
for r in res:
    if r.get("error"): print(f"{r['id']:<52} ERROR {r['error'][:50]}"); continue
    p=r.get("params_total"); p=f"{p/1e9:.1f}B" if p else "?"
    print(f"{r['id']:<52} {p:>7} {str(r.get('license'))[:12]:<12} L={L(r,'num_hidden_layers')} q={L(r,'num_attention_heads')} kv={L(r,'num_key_value_heads')} hd={L(r,'head_dim')} hs={L(r,'hidden_size')} ctx={L(r,'max_position_embeddings')} E={L(r,'num_experts') or L(r,'n_routed_experts')} Et={L(r,'num_experts_per_tok')} moe={L(r,'moe_intermediate_size')} sw={L(r,'sliding_window')} lora={L(r,'kv_lora_rank')}")
    print(f"    arch={r.get('arch')} mtype={r.get('mtype')} base={str(r.get('base'))[:70]} dt={r.get('dt')} created={r.get('created')} dl={r.get('dl')} gated={r.get('gated')} quant={str(r.get('c_quantization_config'))[:60]}")
