# Feidee Home Assistant Integration

将 [飞蛋记账](https://www.feidee.com)（Feidee）云端账本数据同步到 Home Assistant。

## 功能

- 配置向导：手机号 + 密码登录，支持多账本选择
- 触发验证码时会自动下载验证码图片并引导输入
- 每个账本对应一个独立 HA 设备
- 自动刷新（默认 15 分钟，可在选项中调整 300–3600 秒）
- Token 过期自动重登
- 按账本创建设备；配置时自选指标（每个账本 × 每个已选指标 = 一个实体）
- 可选指标：本月/本周/今年 支出与收入、本月结余、今日支出/收入、账本总余额
- 集成「选项」中可后续增删指标或调整刷新间隔

## 安装

### 方式一：HACS 自定义仓库

1. 将本仓库添加到 HACS → 集成 → 自定义仓库
2. 类别选择 **Integration**
3. 安装后重启 Home Assistant
4. 设置 → 设备与服务 → 添加集成 → 搜索 **Feidee**

### 方式二：手动复制

将 `custom_components/feidee` 目录复制到 Home Assistant 配置目录下的 `custom_components/` 中，然后重启。

## 配置

1. 输入飞蛋账号（手机号）和密码
2. 如遇验证码，按提示完成校验
3. 从列表中选择要同步的账本
4. （可选）在集成「选项」中调整刷新间隔

## 注意事项

- 本集成通过非官方 Web API 访问数据，仅供个人使用
- 密码存储在 Home Assistant 配置条目中（本地加密存储）
- 飞蛋无 refresh token，token 失效时会自动用密码重新登录
- 验证码流程依赖飞蛋前端接口，若接口调整可能需要更新集成

## 开发

基于飞蛋 Web API 逆向实现，核心客户端见 `custom_components/feidee/api.py`。
