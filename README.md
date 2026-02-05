## For private use only. Unauthorized use or distribution is strictly prohibited.
[本地托管代码添加到GitHub](https://docs.github.com/zh/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github)

初始化仓库
```bash
git init
````

添加所有文件
```bash
git add .
```

修改分支名称
```bash
git branch -m "main"
```

使用 rebase 策略合并代码
```bash
git pull origin main --rebase
```

提交 commit 信息
```bash
git commit -m "Update"
```

推送至远程仓库
```bash
git push origin main
```