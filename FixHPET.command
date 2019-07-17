#!/usr/bin/env bash

# Get the curent directory, the script name
# and the script name with "py" substituted for the extension.
args="$@"
dir="${0%/*}"
script="${0##*/}"
target="${script%.*}.py"
NL=$'\n'

# use_py3:
#   TRUE  = Use if found, use py2 otherwise
#   FALSE = Use py2
#   FORCE = Use py3
use_py3="FORCE"

# Check to see if we need to force based on
# macOS version. 10.15 has a dummy python3 version
# that can trip up some py3 detection in other scripts.
current_os="$(sw_vers -productVersion)"
if [ "$(echo "$current_os < 10.15" |bc)" == "1" ]; then
    # We're under 10.15, switch to TRUE instead
    use_py3="TRUE"
fi

tempdir=""

get_remote_py_version () {
    local pyurl= py_html= py_vers= py_num="3"
    pyurl="https://www.python.org/downloads/mac-osx/"
    py_html="$(curl -v $pyurl 2>&1)"
    if [ "$use_py3" == "" ]; then
        use_py3="TRUE"
    fi
    if [ "$use_py3" == "FALSE" ]; then
        py_num="2"
    fi
    py_vers="$(echo "$py_html" | grep -i "Latest Python $py_num Release" | awk '{print $8}' | cut -d'<' -f1)"
    echo "$py_vers"
}

download_py () {
    local vers="$1" url=
    clear
    echo "  ###                        ###"
    echo " #     Downloading Python     #"
    echo "###                        ###"
    echo
    if [ "$vers" == "" ]; then
        echo "Gathering latest version..."
        vers="$(get_remote_py_version)"
    fi
    if [ "$vers" == "" ]; then
        # Didn't get it still - bail
        print_error
    fi
    echo "Located Version:  $vers"
    echo
    echo "Building download url..."
    url="https://www.python.org/ftp/python/$vers/python-$vers-macosx10.9.pkg"
    echo " - $url"
    echo
    echo "Downloading..."
    echo
    # Create a temp dir and download to it
    tempdir="$(mktemp -d 2>/dev/null || mktemp -d -t 'tempdir')"
    curl "$url" -o "$tempdir/python.pkg"
    echo
    echo "Running python install package..."
    sudo installer -pkg "$tempdir/python.pkg" -target /
    echo
    vers_folder="Python $(echo "$vers" | cut -d'.' -f1 -f2)"
    if [ -f "/Applications/$vers_folder/Install Certificates.command" ]; then
        # Certs script exists - let's execute that to make sure our certificates are updated
        echo "Updating Certificates..."
        echo
        "/Applications/$vers_folder/Install Certificates.command"
        echo 
    fi
    echo "Cleaning up..."
    cleanup
    echo
    # Now we check for py again
    echo "Rechecking py..."
    downloaded="TRUE"
    main
}

cleanup () {
    if [ -d "$tempdir" ]; then
        rm -Rf "$tempdir"
    fi
}

print_error() {
    clear
    cleanup
    echo "  ###                      ###"
    echo " #     Python Not Found     #"
    echo "###                      ###"
    echo
    echo "Python is not installed or not found in your PATH var."
    echo
    echo "Please go to https://www.python.org/downloads/mac-osx/"
    echo "to download and install the latest version."
    echo
    exit 1
}

print_target_missing() {
    clear
    cleanup
    echo "  ###                      ###"
    echo " #     Target Not Found     #"
    echo "###                      ###"
    echo
    echo "Could not locate $target!"
    echo
    exit 1
}

get_local_python_version() {
    # $1 = Python bin name (defaults to python3)
    # Echoes the path to the highest version of the passed python bin if any
    local py_name="$1" max_version= python= python_version= python_path=
    if [ "$py_name" == "" ]; then
        py_name="python3"
    fi
    py_list="$(which -a "$py_name" 2>/dev/null)"
    # Build a newline separated list from the whereis output too
    for python in "$(whereis "$py_name" 2>/dev/null)"; do
        if [ "$py_list" == "" ]; then
            py_list="$python"
        else
            py_list="$py_list${NL}$python"
        fi
    done
    # Walk that newline separated list
    while read python; do
        if [ "$python" == "" ]; then
            # Got a blank line - skip
            continue
        fi
        python_version="$($python -V 2>&1 | cut -d' ' -f2 | grep -E "[\d.]+")"
        if [ "$python_version" == "" ]; then
            # Didn't find a py version - skip
            continue
        fi
        # Got the py version - compare to our max
        if [ "$max_version" == "" ] || [ "$(echo $python_version > $max_version |bc)" == "1" ]; then
            # Max not set, or less than the current - update it
            max_version="$python_version"
            python_path="$python"
        fi
    done <<< "$py_list"
    echo "$python_path"
}

prompt_and_download() {
    if [ "$downloaded" != "FALSE" ]; then
        # We already tried to download - just bail
        print_error
    fi
    clear
    echo "  ###                      ###"
    echo " #     Python Not Found     #"
    echo "###                      ###"
    echo
    target_py="Python 3"
    printed_py="Python 2 or 3"
    if [ "$use_py3" == "FORCE" ]; then
        printed_py="Python 3"
    elif [ "$use_py3" == "FALSE" ]; then
        target_py="Python 2"
        printed_py="Python 2"
    fi
    echo "Could not locate $printed_py!"
    echo
    echo "This script requires $printed_py to run."
    echo
    while true; do
        read -p "Would you like to install the latest $target_py now? (y/n):  " yn
        case $yn in
            [Yy]* ) download_py;break;;
            [Nn]* ) print_error;;
        esac
    done
}

main() {
    clear
    python=
    version=
    # Verify our target exists
    if [ ! -f "$dir/$target" ]; then
        # Doesn't exist
        print_target_missing
    fi
    if [ "$use_py3" == "" ]; then
        use_py3="TRUE"
    fi
    if [ "$use_py3" != "FALSE" ]; then
        # Check for py3 first
        python="$(get_local_python_version python3)"
        version="$($python -V 2>&1 | cut -d' ' -f2 | grep -E "[\d.]+")"
    fi
    if [ "$use_py3" != "FORCE" ] && [ "$python" == "" ]; then
        # We aren't using py3 explicitly, and we don't already have a path
        python="$(get_local_python_version python2)"
        version="$($python -V 2>&1 | cut -d' ' -f2 | grep -E "[\d.]+")"
    fi
    if [ "$python" == "" ]; then
        # Didn't ever find it - prompt
        prompt_and_download
        return 1
    fi
    # Found it - start our script and pass all args
    "$python" "$dir/$target" $args
}

downloaded="FALSE"
trap cleanup EXIT
main
