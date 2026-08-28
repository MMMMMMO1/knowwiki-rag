def hard_cut(s,chunk_size):
    result = []
    for i in range(0,len(s),chunk_size):
        result.append(s[i:i+chunk_size])
    return  result
print(hard_cut("adajhbcngwh", 3))
