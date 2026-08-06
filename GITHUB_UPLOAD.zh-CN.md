# 上传到 GitHub

## 创建仓库

在 GitHub 新建一个空仓库，建议名称：

```text
pdf-text-repair
```

不要在网页端预先创建 README、License 或 `.gitignore`，这些文件已经包含在源码中。

## 终端上传

进入解压后的项目目录：

```bash
cd "$HOME/Downloads/pdf-text-repair"
git init
git branch -M main
git add .
git commit -m "Initial public beta"
git remote add origin https://github.com/YOUR_USERNAME/pdf-text-repair.git
git push -u origin main
```

将 `YOUR_USERNAME` 替换为自己的 GitHub 用户名。

## 使用 GitHub CLI

已经安装 `gh` 时可以执行：

```bash
cd "$HOME/Downloads/pdf-text-repair"
git init
git branch -M main
git add .
git commit -m "Initial public beta"
gh repo create pdf-text-repair --public --source=. --remote=origin --push
```

## 上传后检查

1. 确认 Actions 中的 CI 工作流开始运行。
2. 确认仓库中没有书籍 PDF、OCR 模型、输出文件、个人路径或隐私日志。
3. 在 Settings → General 中启用 Issues。
4. 在 Settings → Security 中启用 Dependabot alerts。
5. 准备发布版本时创建标签：

```bash
git tag v0.2.2
git push origin v0.2.2
```

标签会触发 macOS 构建工作流。产物未经 Apple 签名和公证，公开下载页需要明确说明这一点。

## npm 锁文件

仓库当前允许直接使用 `npm install`。首次在网络正常的 Mac 上运行后会生成 `package-lock.json`，建议将其提交，以便后续改用 `npm ci` 获得更稳定的依赖安装结果。
