# 静态链接加密库逆向

适用场景：网络层能看到密文，但 `sym` / `asym` / `digest` 分类没有事件。
典型目标：CryptoSwift、静态链接 OpenSSL/BoringSSL、自研分组密码或大数实现。

## 1. 先确认「真的没抓到」

- `get_capture_coverage`：区分「没命中」和「没装 hook」，看 `blind_spots`。
- `query_events(category:"all", query:"CCCrypt")` / `SecKey` / `EVP_`：确认标准 API 无事件。
- `query_events(category:"net")`：网络层已有端点/密文，说明请求确实发出。

## 2. 判断加密实现

- `list_loaded_images` / `get_macho_info`：找 OpenSSL、BoringSSL、CryptoSwift 线索。
- `list_imports`：如果完全没有 `CCCrypt` / `SecKey*` / `EVP_*`，但业务确实加密，基本是静态实现。
- `list_functions(query:"...")` / `find_string_refs("AES")`：strip 后可能只剩 `sub_<addr>`。

目标不是逆出完整算法，而是找到「key 进入加密库的第一个可观测点」。

## 3. 找「指针 + 长度」导入

优先枚举：`mlock`、`memcpy`/`memmove`、`read`/`recv`/`send`/`SSL_write`、
`getrandom`/`SecRandomCopyBytes`/`arc4random_buf`、`memset`/`bzero`。

先 `list_images` 拿 `image_index`，再 `list_imports(image_index, query:"mlock")`
确认符号在导入表。**不在导入表就不能 fishhook**，不要用 inline hook 绕过。

## 4. 命中瞬间抓内存

`capture_memory` 在 thunk handler 内、原函数返回前拷贝，不是事后 `read_memory`。

```json
{
  "name": "hook_import",
  "arguments": {
    "symbol": "mlock",
    "label": "crypto-key-buffer",
    "capture_memory": { "ptr_arg": 0, "len_arg": 1, "max_bytes": 4096 }
  }
}
```

- `ptr_arg` / `len_arg` 是 x 寄存器索引（0..8）。
- `len_arg: -1` 时用 `max_bytes` 固定长度。
- `hook_method` 同理：x0=self，x1=_cmd，x2..=方法参数。
- 结果在事件的 `input` / `inputHex` / `inputUtf8` / `inputDump`。

事后回读常见结果是零、堆头或别人的数据，因为缓冲区已经释放/复用。

## 5. 验证闭环

1. 用候选 key 解密网络密文，得到结构合理的明文。
2. 用同一 key、模式、填充回加密，密文逐字节一致。
3. 同一进程多次触发，换 `sessionId` / nonce / 时间戳：
   - key 不变 -> 硬编码常量或长生命周期密钥；
   - 每次都变 -> 会话密钥，继续找协商或随机源。
4. 静态 dump 里的常量只能作为候选；动态捕获 + 回加密闭环才算证明。

## 6. 抓不到时的边界

- key 完全在静态库内部生成，只存在于寄存器/栈，且不经过任何导入函数；
- 加密库把 `mlock` / `memcpy` 全部内联（LTO），导入表没有可 hook 的点；
- 明文只在自研网络栈内部（裸 socket + 自带 TLS）。

这时优先找调用层（Swift/ObjC wrapper）用 `hook_method(describe_args:true)`，
或找随机源、序列化边界、日志/缓存落盘等旁路；不要为了一个 key 引入
inline hook / trampoline。

## 7. 实战：山东航空 CryptoSwift

- 标准 `sym` / `asym` hook 全空，网络 body 是 `{"param": Base64(...)}`；
- `list_imports` 找到 `mlock`，`hook_import` + `capture_memory` 命中 16 字节 ASCII key；
- 同进程三次登录，`sessionId` / `deviceKey` / `timeStamp` 变化但 key 不变；
- AES-128-ECB-PKCS7 解密得到业务 JSON，回加密逐字节一致。

详细记录见 IOSDecryptHub 源码仓 `docs/analysis/山东航空-登录加密.md` 与
`docs/analysis/逆向技巧-静态链接加密库.md`。
