def split_text(
        text:str,
        chunk_size:int=50,
        chunk_overlap:int=10
):
    chunks=[]
    start=0
    while start<len(text):
        end=start+chunk_size

        chunk=text[start:end]

        chunks.append(chunk)

        start=end-chunk_overlap

    return chunks
