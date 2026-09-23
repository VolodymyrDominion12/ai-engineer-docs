import json, urllib.request, sys
UA={"User-Agent":"Mozilla/5.0"}
def get(u):
    r=urllib.request.Request(u,headers=UA)
    with urllib.request.urlopen(r,timeout=60) as f: return f.read().decode('utf-8','replace')
def leaves(d, pre=""):
    out={}
    for k,v in d.items():
        p=f"{pre}{k}"
        if isinstance(v,dict): out.update(leaves(v,p+"."))
        elif isinstance(v,list) and len(str(v))>80: out[p]=f"list(len={len(v)})"
        else: out[p]=v
    return out
for mid in sys.argv[1:]:
    print("="*100); print("MODEL:", mid)
    try:
        c=json.loads(get(f"https://huggingface.co/{mid}/raw/main/config.json"))
    except Exception as e:
        print("  ERR", e); continue
    keep=("num_hidden_layers","num_attention_heads","num_key_value_heads","head_dim","hidden_size",
      "max_position_embeddings","vocab_size","tie_word_embeddings","expert","intermediate_size",
      "sliding_window","torch_dtype","kv_lora_rank","qk_nope","qk_rope","v_head_dim","rope_scaling",
      "layer_types","full_attention","linear_","model_type","architectures","quantization","vision",
      "n_group","topk","norm_topk","dense","shared","attention_bias","mlp_only","first_k","eos","bos")
    for k,v in leaves(c).items():
        if any(s in k for s in keep): print(f"  {k} = {v}")
