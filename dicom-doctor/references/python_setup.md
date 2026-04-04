# Python 环境安装指南

> 本步骤由宿主 AI 自动判断——如果执行 `python --version` 或 `python3 --version` 能返回 >= 3.8 的版本号，直接跳过。**不要问用户"你装了 Python 吗"，自己检测。**

**如果检测到 Python 不可用或版本过低**，宿主 AI 必须按以下流程自动安装，不得暂停询问用户：

## macOS

```bash
# 方案1（推荐）：Homebrew
brew install python3

# 方案2：官方安装包（如果没有 brew）
curl -O https://www.python.org/ftp/python/3.12.0/python-3.12.0-macos11.pkg
sudo installer -pkg python-3.12.0-macos11.pkg -target /
```

## Windows（PowerShell）

```powershell
# 方案1（推荐）：winget（Windows 10/11 自带）
winget install Python.Python.3.12 --accept-package-agreements --accept-source-agreements

# 方案2：从淘宝镜像下载安装包（如果 winget 不可用）
Invoke-WebRequest -Uri "https://registry.npmmirror.com/-/binary/python/3.12.0/python-3.12.0-amd64.exe" -OutFile "$env:TEMP\python-installer.exe"
Start-Process "$env:TEMP\python-installer.exe" -ArgumentList '/quiet', 'InstallAllUsers=1', 'PrependPath=1' -Wait
# 安装完成后需要刷新 PATH
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
```

## Linux (Ubuntu/Debian)

```bash
sudo apt update && sudo apt install -y python3 python3-pip
```

## Linux (CentOS/RHEL)

```bash
sudo yum install -y python3 python3-pip
```

> **安装完成后**，重新执行 `python --version` 或 `python3 --version` 验证，确认 >= 3.8 后再进入第 1 步。如果安装失败（比如用户没有管理员权限），在输出中说明情况并建议用户手动安装，但**不要反复询问**。
