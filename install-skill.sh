#!/usr/bin/env bash
set -euo pipefail

REPO_SLUG="eyjian/ai-skills"
DEFAULT_REF="main"
DEFAULT_TARGET=".codebuddy/skills"

usage() {
  cat <<'EOF'
用法:
  bash install-skill.sh [选项] <target> [<target>...]
  bash install-skill.sh --list

可安装目标:
  article-team
  subagent-writing-skills
  ai-writing-skills
  topic-scout
  outline-architect
  draft-writer
  tech-reviewer
  final-polisher
  dicom-doctor
  all

选项:
  --target DIR      安装目标目录，默认：./.codebuddy/skills
  --ref REF         仓库分支、标签或提交，默认：main
  --from-local DIR  从本地仓库目录安装，不下载 GitHub 压缩包
  --list            列出所有可安装目标
  -h, --help        显示帮助

示例:
  bash install-skill.sh article-team
  bash install-skill.sh subagent-writing-skills --target /path/to/.codebuddy/skills
  bash install-skill.sh ai-writing-skills dicom-doctor
  curl -fsSL https://raw.githubusercontent.com/eyjian/ai-skills/main/install-skill.sh | bash -s -- all
EOF
}

print_targets() {
  cat <<'EOF'
article-team
subagent-writing-skills
ai-writing-skills
topic-scout
outline-architect
draft-writer
tech-reviewer
final-polisher
dicom-doctor
all
EOF
}

die() {
  echo "错误：$*" >&2
  exit 1
}

add_unique() {
  local item="$1"
  shift
  local existing
  for existing in "$@"; do
    if [[ "$existing" == "$item" ]]; then
      return 1
    fi
  done
  return 0
}

normalize_target() {
  case "$1" in
    article-team|article_team|article-team-writing-skill)
      echo "article-team"
      ;;
    subagent-writing-skills|subagent-writing-skill|subagents|writing-subagents)
      echo "subagent-writing-skills"
      ;;
    ai-writing-skills|writing-all)
      echo "ai-writing-skills"
      ;;
    topic-scout|outline-architect|draft-writer|tech-reviewer|final-polisher|dicom-doctor|all)
      echo "$1"
      ;;
    *)
      return 1
      ;;
  esac
}

expand_target() {
  case "$1" in
    ai-writing-skills)
      printf '%s\n' "subagent-writing-skills" "article-team"
      ;;
    all)
      printf '%s\n' "subagent-writing-skills" "article-team" "dicom-doctor"
      ;;
    *)
      printf '%s\n' "$1"
      ;;
  esac
}

validate_repo_root() {
  local repo_dir="$1"
  [[ -d "$repo_dir/ai-writing-skills" ]] || die "仓库目录缺少 ai-writing-skills：$repo_dir"
  [[ -d "$repo_dir/dicom-doctor" ]] || die "仓库目录缺少 dicom-doctor：$repo_dir"
}

detect_local_repo() {
  local script_source="${BASH_SOURCE[0]:-}"
  [[ -n "$script_source" ]] || return 1
  [[ -f "$script_source" ]] || return 1

  local script_dir
  script_dir="$(cd "$(dirname "$script_source")" && pwd)"

  if [[ -d "$script_dir/ai-writing-skills" ]] && [[ -d "$script_dir/dicom-doctor" ]]; then
    printf '%s\n' "$script_dir"
    return 0
  fi

  return 1
}

download_repo_archive() {
  command -v tar >/dev/null 2>&1 || die "缺少 tar，无法解压仓库归档"

  TEMP_DIR="$(mktemp -d)"
  local archive_path="$TEMP_DIR/repo.tar.gz"
  local extract_dir="$TEMP_DIR/extracted"
  local url="https://codeload.github.com/${REPO_SLUG}/tar.gz/${REF}"

  mkdir -p "$extract_dir"

  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$url" -o "$archive_path"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO "$archive_path" "$url"
  else
    die "当前环境缺少 curl 或 wget，无法下载仓库归档"
  fi

  tar -xzf "$archive_path" -C "$extract_dir"

  SOURCE_REPO="$(find "$extract_dir" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
  [[ -n "$SOURCE_REPO" ]] || die "仓库归档解压失败"
  validate_repo_root "$SOURCE_REPO"
  SOURCE_DESC="GitHub ${REPO_SLUG}@${REF}"
}

prepare_source_repo() {
  if [[ -n "$LOCAL_REPO" ]]; then
    SOURCE_REPO="$(cd "$LOCAL_REPO" && pwd)"
    validate_repo_root "$SOURCE_REPO"
    SOURCE_DESC="本地仓库 $SOURCE_REPO"
    return
  fi

  local detected_repo
  detected_repo="$(detect_local_repo || true)"
  if [[ -n "$detected_repo" ]]; then
    SOURCE_REPO="$detected_repo"
    validate_repo_root "$SOURCE_REPO"
    SOURCE_DESC="本地仓库 $SOURCE_REPO"
    return
  fi

  download_repo_archive
}

copy_dir() {
  local relative_src="$1"
  local dest_name="$2"
  local src_path="$SOURCE_REPO/$relative_src"
  local dest_path="$TARGET_DIR/$dest_name"

  [[ -d "$src_path" ]] || die "源目录不存在：$relative_src"

  rm -rf "$dest_path"
  cp -R "$src_path" "$dest_path"

  if add_unique "$dest_path" "${INSTALLED_PATHS[@]:-}"; then
    INSTALLED_PATHS+=("$dest_path")
  fi
}

install_subagent_bundle() {
  local base="ai-writing-skills/subagent-writing-skills"
  copy_dir "$base/shared-writing-resources" "shared-writing-resources"
  copy_dir "$base/topic-scout" "topic-scout"
  copy_dir "$base/outline-architect" "outline-architect"
  copy_dir "$base/draft-writer" "draft-writer"
  copy_dir "$base/tech-reviewer" "tech-reviewer"
  copy_dir "$base/final-polisher" "final-polisher"
}

install_single_subagent() {
  local name="$1"
  local base="ai-writing-skills/subagent-writing-skills"
  copy_dir "$base/shared-writing-resources" "shared-writing-resources"
  copy_dir "$base/$name" "$name"
}

install_target() {
  case "$1" in
    article-team)
      copy_dir "ai-writing-skills/agent-team-writing-skill/article-team" "article-team"
      ;;
    subagent-writing-skills)
      install_subagent_bundle
      ;;
    topic-scout|outline-architect|draft-writer|tech-reviewer|final-polisher)
      install_single_subagent "$1"
      ;;
    dicom-doctor)
      copy_dir "dicom-doctor" "dicom-doctor"
      ;;
    *)
      die "内部错误：不支持的安装目标 $1"
      ;;
  esac
}

cleanup() {
  if [[ -n "${TEMP_DIR:-}" ]] && [[ -d "$TEMP_DIR" ]]; then
    rm -rf "$TEMP_DIR"
  fi
}

trap cleanup EXIT

TARGET_DIR="$DEFAULT_TARGET"
REF="$DEFAULT_REF"
LOCAL_REPO=""
TEMP_DIR=""
SOURCE_REPO=""
SOURCE_DESC=""
REQUESTED_TARGETS=()
FINAL_TARGETS=()
INSTALLED_PATHS=()
SHOW_LIST=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target)
      [[ $# -ge 2 ]] || die "--target 缺少参数"
      TARGET_DIR="$2"
      shift 2
      ;;
    --ref)
      [[ $# -ge 2 ]] || die "--ref 缺少参数"
      REF="$2"
      shift 2
      ;;
    --from-local)
      [[ $# -ge 2 ]] || die "--from-local 缺少参数"
      LOCAL_REPO="$2"
      shift 2
      ;;
    --list)
      SHOW_LIST=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      while [[ $# -gt 0 ]]; do
        REQUESTED_TARGETS+=("$1")
        shift
      done
      ;;
    -*)
      die "不支持的选项：$1"
      ;;
    *)
      REQUESTED_TARGETS+=("$1")
      shift
      ;;
  esac
done

if [[ "$SHOW_LIST" -eq 1 ]]; then
  print_targets
  exit 0
fi

[[ "${#REQUESTED_TARGETS[@]}" -gt 0 ]] || die "请至少指定一个安装目标；可用 --list 查看全部目标"

for raw_target in "${REQUESTED_TARGETS[@]}"; do
  normalized_target="$(normalize_target "$raw_target" || true)"
  [[ -n "$normalized_target" ]] || die "未知安装目标：$raw_target"

  while IFS= read -r expanded_target; do
    [[ -n "$expanded_target" ]] || continue
    if add_unique "$expanded_target" "${FINAL_TARGETS[@]:-}"; then
      FINAL_TARGETS+=("$expanded_target")
    fi
  done < <(expand_target "$normalized_target")
done

prepare_source_repo
mkdir -p "$TARGET_DIR"
TARGET_DIR="$(cd "$TARGET_DIR" && pwd)"

for install_name in "${FINAL_TARGETS[@]}"; do
  install_target "$install_name"
done

echo "安装完成。"
echo "来源：$SOURCE_DESC"
echo "目标目录：$TARGET_DIR"
echo "已安装目标："
for install_name in "${FINAL_TARGETS[@]}"; do
  echo "  - $install_name"
done

echo "写入目录："
for path in "${INSTALLED_PATHS[@]}"; do
  echo "  - $path"
done
