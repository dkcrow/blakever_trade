#!/bin/bash
# Blakever 项目每日自动 Git 提交脚本
# 每天凌晨执行，自动检测并提交项目改动

PROJECT_DIR="/data/workspace/blakever_stock_analyze"
LOG_FILE="/data/workspace/blakever_stock_analyze/auto_git_commit.log"

echo "===== $(date '+%Y-%m-%d %H:%M:%S') 自动Git提交开始 =====" >> "$LOG_FILE"

cd "$PROJECT_DIR" || { echo "目录不存在: $PROJECT_DIR" >> "$LOG_FILE"; exit 1; }

# 检查是否有改动（包括未跟踪文件）
CHANGED=$(git status --porcelain | grep -v '__pycache__' | grep -v '.pyc' | head -50)

if [ -z "$CHANGED" ]; then
    echo "无项目改动，跳过提交" >> "$LOG_FILE"
    exit 0
fi

echo "检测到以下改动：" >> "$LOG_FILE"
echo "$CHANGED" >> "$LOG_FILE"

# 添加所有改动（排除 __pycache__ 和 .pyc）
git add -A
git reset -- '**/__pycache__/' '*.pyc' '*.pyo' 2>/dev/null

# 生成提交信息：包含日期和改动摘要
TODAY=$(date '+%Y-%m-%d')
CHANGED_COUNT=$(echo "$CHANGED" | wc -l)
ADDED=$(echo "$CHANGED" | grep -c '^??' || true)
MODIFIED=$(echo "$CHANGED" | grep -c '^ M\|^M ' || true)
DELETED=$(echo "$CHANGED" | grep -c '^ D\|^D ' || true)

COMMIT_MSG="chore: ${TODAY} 自动提交 - ${CHANGED_COUNT}个文件改动(修改${MODIFIED}/新增${ADDED}/删除${DELETED})"

# 提交
git commit -m "$COMMIT_MSG" >> "$LOG_FILE" 2>&1
COMMIT_RESULT=$?

if [ $COMMIT_RESULT -eq 0 ]; then
    echo "提交成功: $COMMIT_MSG" >> "$LOG_FILE"
    # 推送到远程
    git push origin HEAD >> "$LOG_FILE" 2>&1
    PUSH_RESULT=$?
    if [ $PUSH_RESULT -eq 0 ]; then
        echo "推送成功" >> "$LOG_FILE"
    else
        echo "⚠️ 推送失败，将在下次重试" >> "$LOG_FILE"
    fi
elif [ $COMMIT_RESULT -eq 1 ]; then
    echo "无内容需要提交（可能已提交）" >> "$LOG_FILE"
else
    echo "❌ 提交失败，退出码: $COMMIT_RESULT" >> "$LOG_FILE"
fi

echo "===== $(date '+%Y-%m-%d %H:%M:%S') 自动Git提交结束 =====" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"
