# Git 同步说明

远程仓库：https://github.com/maoyuecong682/ICML2027_agent

在当前工作区根目录打开终端。每次修改后提交并推送：

```powershell
git status
git add -A
git commit -m "说明这次修改"
git push
```

开始工作前，可运行 `git pull --rebase` 获取远程更新；执行前先提交本地修改。

在新电脑上获取完整工作区（需先安装 Git 和 Git LFS）：

```powershell
git lfs install
git clone --recurse-submodules https://github.com/maoyuecong682/ICML2027_agent.git
cd ICML2027_agent
git lfs pull
```

`longrun/_llmprivacy` 保留为指向其原始版本的 Git 子模块。已有克隆可运行
`git submodule update --init --recursive` 获取子模块内容。修改子模块时，需要先在
子模块中提交并将提交推送到有写入权限的远程仓库，再在主仓库提交新的版本引用。

压缩包通过 Git LFS 管理，日常仍使用相同的 `git add`、`git commit` 和 `git push` 命令。
Python 虚拟环境、缓存、本地编辑器状态和 `.env` 密钥文件不会上传；原有子目录的
`.gitignore` 规则也继续生效。

当前电脑的本地仓库使用正在运行的代理 `http://127.0.0.1:7897` 连接 GitHub，
同步时需保持代理启动。若以后使用可直连的网络，可运行
`git config --local --unset http.proxy` 移除此设置；新克隆不会继承该本地设置。

API 密钥保存在各实验目录的本地 `.env` 中。换电脑后，将相应 `.env.example`
复制为 `.env` 并填入自己的 `DEEPSEEK_API_KEY`，或设置同名环境变量。
`pipeline` 和 `longrun` 的配置通过 `python-dotenv` 读取本地 `.env`；新环境需安装该依赖
（`pipeline/requirements.txt` 已包含它）。
