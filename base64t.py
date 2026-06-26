import base64

# 將 憑證_cert.pfx 替換為你的憑證檔名
with open("憑證.pfx", "rb") as f:
    encoded_string = base64.b64encode(f.read()).decode("utf-8")

# 將結果存成一個 txt 檔方便複製
with open("cert_base64.txt", "w") as f:
    f.write(encoded_string)
    
print("轉換完成！請打開 cert_base64.txt 並複製裡面的全部文字。")