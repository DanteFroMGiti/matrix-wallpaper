#!/usr/bin/env bash
# Download a verified release, install distribution dependencies, then install as the user.
set -euo pipefail

MATRIX_REPOSITORY='DanteFroMGiti/matrix-wallpaper'
MATRIX_VERSION='3.5.0'

matrix_packages() {
    local distribution=" $1 "
    if [[ "$distribution" == *' arch '* || "$distribution" == *' cachyos '* || "$distribution" == *' manjaro '* ]]; then
        MATRIX_MANAGER=pacman
        MATRIX_PACKAGES=(python python-gobject python-cairo python-pillow python-numpy python-xlib gtk3 libappindicator gcc pkgconf libx11 libxext libxcomposite cairo pango libepoxy xfconf xorg-xrandr ffmpeg libpulse systemd desktop-file-utils curl tar)
    elif [[ "$distribution" == *' debian '* || "$distribution" == *' ubuntu '* || "$distribution" == *' linuxmint '* ]]; then
        MATRIX_MANAGER=apt-get
        MATRIX_PACKAGES=(python3 python3-gi python3-gi-cairo python3-cairo python3-pil python3-numpy python3-xlib gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1 build-essential pkg-config libx11-dev libxext-dev libxcomposite-dev libcairo2-dev libpango1.0-dev libepoxy-dev xfconf x11-xserver-utils ffmpeg pulseaudio-utils systemd desktop-file-utils curl tar)
    else
        printf 'Автоустановка зависимостей поддерживает Arch/CachyOS/Manjaro и Debian/Ubuntu/Mint.\nДля другой системы используйте архив релиза и install.py --check.\n' >&2
        return 1
    fi
}

matrix_install_packages() {
    local -a privileged=(sudo)
    command -v sudo >/dev/null || { printf 'Нужен sudo для установки системных зависимостей.\n' >&2; return 1; }
    printf 'Устанавливаю зависимости через %s (может понадобиться пароль sudo)…\n' "$MATRIX_MANAGER"
    case "$MATRIX_MANAGER" in
        pacman) "${privileged[@]}" pacman -S --needed --noconfirm "${MATRIX_PACKAGES[@]}" ;;
        apt-get)
            "${privileged[@]}" apt-get update || return
            "${privileged[@]}" apt-get install -y --no-install-recommends "${MATRIX_PACKAGES[@]}"
            ;;
    esac
}

matrix_download() {
    local directory=$1 archive="matrix-wallpaper-${MATRIX_VERSION}.tar.gz"
    # gh handles private repository access without copying tokens into URLs or arguments.
    if command -v gh >/dev/null && gh api "repos/$MATRIX_REPOSITORY" --silent >/dev/null 2>&1; then
        gh release download "v$MATRIX_VERSION" --repo "$MATRIX_REPOSITORY" --dir "$directory" --pattern "$archive" --pattern "$archive.sha256"
    else
        command -v curl >/dev/null || { printf 'Для загрузки нужен curl либо авторизованный GitHub CLI (gh).\n' >&2; return 1; }
        local url="https://github.com/$MATRIX_REPOSITORY/releases/download/v$MATRIX_VERSION"
        curl --fail --show-error --location --proto '=https' --proto-redir '=https' --retry 3 --output "$directory/$archive" "$url/$archive" || return
        curl --fail --show-error --location --proto '=https' --proto-redir '=https' --retry 3 --output "$directory/$archive.sha256" "$url/$archive.sha256"
    fi
}

matrix_verify_archive() {
    local directory=$1 archive="matrix-wallpaper-${MATRIX_VERSION}.tar.gz"
    # Never process arbitrary filenames from a checksum file.
    local digest checksum_name rest actual_digest
    read -r digest checksum_name rest < "$directory/$archive.sha256" || return
    [[ "$digest" =~ ^[a-fA-F0-9]{64}$ && "$checksum_name" == "$archive" && -z "$rest" ]] || { printf 'Некорректный файл контрольной суммы.\n' >&2; return 1; }
    actual_digest=$(sha256sum "$directory/$archive") || return
    [[ "${actual_digest%% *}" == "${digest,,}" ]] || { printf 'Контрольная сумма архива не совпадает. Установка отменена.\n' >&2; return 1; }
}

matrix_main() (
    local dry_run=false skip_dependencies=false target_home=''
    while (( $# )); do
        case "$1" in
            --dry-run) dry_run=true ;;
            --skip-dependencies) skip_dependencies=true ;;
            --home)
                (( $# >= 2 )) || { printf 'После --home нужен путь.\n' >&2; return 2; }
                target_home=$2; shift ;;
            --help|-h)
                printf 'Установка Матричных обоев для XFCE/X11.\n  --dry-run            показать план без изменений и загрузок\n  --skip-dependencies  зависимости уже установлены\n  --home ПУТЬ          установить в отдельный домашний каталог\n'
                return 0 ;;
            *) printf 'Неизвестный параметр: %s\n' "$1" >&2; return 2 ;;
        esac
        shift
    done
    [[ $(uname -s) == Linux ]] || { printf 'Приложение требует Linux с XFCE/X11.\n' >&2; return 1; }
    local ID='' ID_LIKE=''
    # /etc/os-release is maintained by the operating system.
    source /etc/os-release
    matrix_packages "$ID $ID_LIKE"
    printf 'Матричные обои %s · %s\n' "$MATRIX_VERSION" "${PRETTY_NAME:-$ID}"
    if "$dry_run"; then
        printf 'Релиз: https://github.com/%s/releases/tag/v%s\n' "$MATRIX_REPOSITORY" "$MATRIX_VERSION"
        if ! "$skip_dependencies"; then
            printf 'Системные пакеты (%s):' "$MATRIX_MANAGER"
            printf ' %q' "${MATRIX_PACKAGES[@]}"
            printf '\n'
        fi
        printf 'Проверка SHA-256 → распаковка → python3 install.py --check → установка для текущего пользователя.\n'
        return 0
    fi
    (( EUID != 0 )) || { printf 'Запускайте команду обычным пользователем, без sudo перед bash. Для системных пакетов установщик сам вызовет sudo.\n' >&2; return 1; }
    [[ ${XDG_SESSION_TYPE:-x11} != wayland ]] || { printf 'Сначала войдите в сеанс XFCE/X11. Wayland пока не поддерживается.\n' >&2; return 1; }
    command -v xfdesktop >/dev/null || { printf 'Сначала установите рабочий стол XFCE и войдите в сеанс X11.\n' >&2; return 1; }
    command -v systemctl >/dev/null && systemctl --user show-environment >/dev/null || { printf 'Нужен работающий пользовательский systemd в обычном сеансе пользователя.\n' >&2; return 1; }
    local workspace archive="matrix-wallpaper-${MATRIX_VERSION}.tar.gz"
    workspace=$(mktemp -d -t matrix-wallpaper-install.XXXXXXXX)
    trap 'rm -rf -- "$workspace"' EXIT
    printf 'Загружаю релиз…\n'
    if ! matrix_download "$workspace"; then
        printf 'Не удалось загрузить релиз. Если репозиторий закрыт, установите gh и войдите командой gh auth login с доступом к репозиторию.\n' >&2
        return 1
    fi
    matrix_verify_archive "$workspace"
    if ! "$skip_dependencies"; then matrix_install_packages; fi
    tar -xzf "$workspace/$archive" -C "$workspace"
    local package="$workspace/matrix-wallpaper-$MATRIX_VERSION"
    /usr/bin/python3 "$package/install.py" --check
    local -a install_args=(--update)
    if [[ -n "$target_home" ]]; then install_args+=(--home "$target_home"); fi
    /usr/bin/python3 "$package/install.py" "${install_args[@]}"
    printf '\nГотово. Откройте «Матричные обои» в меню приложений. Руководство — F1.\n'
    printf 'Команда запуска: %s/.local/bin/matrix-wallpaper\n' "${target_home:-$HOME}"
)

if [[ ${BASH_SOURCE[0]:-} == "$0" || -z ${BASH_SOURCE[0]:-} ]]; then
    matrix_main "$@"
fi
