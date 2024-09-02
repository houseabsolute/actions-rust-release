#!/usr/bin/perl

use v5.30;
use strict;
use warnings;
no warnings 'experimental::signatures';
use feature 'signatures';
use autodie;

use FindBin qw( $Bin );
use File::Spec;
use lib File::Spec->catdir( $Bin, 'lib' );

use Cwd            qw( abs_path );
use File::Basename qw( basename );
use File::Copy     qw( copy );
use File::Temp     qw( tempdir );
use Getopt::Long;

sub main {
    GetOptions(
        'executable-name=s' => \my $executable_name,
        'target=s'          => \my $target,
        'archive-name=s'    => \my $archive_name,
        'changes-file=s'    => \my $changes_file,
        'extra-files=s'     => \my $extra_files,
    );

    if ( !$executable_name ) {
        die 'The --executable-name option is required.';
    }

    if ( !( $target || $archive_name ) ) {
        die 'You must provide either a target or archive-name when using this action.';
    }

    if ( $changes_file && !-f $changes_file ) {
        die "Changes file '$changes_file' does not exist.";
    }

    if ( !$archive_name ) {
        $archive_name = $executable_name . q{-} . target_to_archive_name($target);
    }

    my $archive_extension = $ENV{RUNNER_OS} eq 'Windows' ? '.zip' : '.tar.gz';
    my $archive_file = File::Spec->catfile( abs_path('.'), $archive_name . $archive_extension );

    $executable_name .= '.exe' if $ENV{RUNNER_OS} eq 'Windows';

    my @look_for = (
        File::Spec->catfile( 'target', $target,   'release', $executable_name ),
        File::Spec->catfile( 'target', 'release', $executable_name )
    );
    my @files;
    for my $file (@look_for) {
        if ( -f $file ) {
            say "Found executable at $file";
            push @files, $file;
            last;
        }
    }

    if ( !@files ) {
        my $msg = "Could not find executable in any of:\n";
        $msg .= "  $_\n" for @look_for;
        die $msg;
    }

    if ($extra_files) {
        $extra_files =~ s/^\s+|\s+$//gs;
        push @files, split /\n/, $extra_files;
    }
    else {
        push @files, $changes_file;
        push @files, glob 'README*';
    }

    my $td = tempdir( CLEANUP => 1 );
    for my $file (@files) {
        copy( $file => $td )
            or die "Cannot copy $file => $td: $!";
    }

    chdir $td;

    my @cmd
        = $ENV{RUNNER_OS} eq 'Windows'
        ? ( '7z', 'a', $archive_file, glob('*') )
        : ( 'tar', 'czf', $archive_file, glob('*') );

    say "Running [@cmd]";
    system(@cmd);

    open my $fh, '>>', $ENV{GITHUB_OUTPUT};
    my $archive_basename = basename($archive_file);
    say {$fh} "archive-basename=$archive_basename";
    close $fh;
}

sub target_to_archive_name($target) {
    my ( $cpu, @rest ) = split /-/, $target;
    $cpu =~ s/aarch64/arm64/;

    if ( $rest[0] =~ /^(?:apple|pc|sun|unknown)$/ ) {
        shift @rest;
    }
    my $os = shift @rest;

    # If there's more it's something like "-gnu" or "-msvc".
    if (@rest) {
        $os .= '-' . $rest[0];
    }

    unless ( $os =~ s/darwin/macOS/
        || $os =~ s/freebsd/FreeBSD/
        || $os =~ s/ios/iOS/
        || $os =~ s/netbsd/NetBSD/
        || $os =~ s/openbsd/OpenBSD/ ) {

        $os = ucfirst $os;
    }

    return "$os-$cpu";
}

sub test {
    require Test::More;
    Test::More->import;

    my %tests = (
        'aarch64-apple-darwin'                => 'macOS-arm64',
        'aarch64-apple-ios'                   => 'iOS-arm64',
        'aarch64-apple-ios-sim'               => 'iOS-sim-arm64',
        'aarch64-linux-android'               => 'Linux-android-arm64',
        'aarch64-pc-windows-gnullvm'          => 'Windows-gnullvm-arm64',
        'aarch64-pc-windows-msvc'             => 'Windows-msvc-arm64',
        'aarch64-unknown-fuchsia'             => 'Fuchsia-arm64',
        'aarch64-unknown-linux-gnu'           => 'Linux-gnu-arm64',
        'aarch64-unknown-linux-musl'          => 'Linux-musl-arm64',
        'aarch64-unknown-linux-ohos'          => 'Linux-ohos-arm64',
        'arm-linux-androideabi'               => 'Linux-androideabi-arm',
        'arm-unknown-linux-gnueabi'           => 'Linux-gnueabi-arm',
        'arm-unknown-linux-gnueabihf'         => 'Linux-gnueabihf-arm',
        'arm-unknown-linux-musleabi'          => 'Linux-musleabi-arm',
        'arm-unknown-linux-musleabihf'        => 'Linux-musleabihf-arm',
        'armv5te-unknown-linux-gnueabi'       => 'Linux-gnueabi-armv5te',
        'armv5te-unknown-linux-musleabi'      => 'Linux-musleabi-armv5te',
        'armv7-linux-androideabi'             => 'Linux-androideabi-armv7',
        'armv7-unknown-linux-gnueabi'         => 'Linux-gnueabi-armv7',
        'armv7-unknown-linux-gnueabihf'       => 'Linux-gnueabihf-armv7',
        'armv7-unknown-linux-musleabi'        => 'Linux-musleabi-armv7',
        'armv7-unknown-linux-musleabihf'      => 'Linux-musleabihf-armv7',
        'armv7-unknown-linux-ohos'            => 'Linux-ohos-armv7',
        'i586-pc-windows-msvc'                => 'Windows-msvc-i586',
        'i586-unknown-linux-gnu'              => 'Linux-gnu-i586',
        'i586-unknown-linux-musl'             => 'Linux-musl-i586',
        'i686-linux-android'                  => 'Linux-android-i686',
        'i686-pc-windows-gnu'                 => 'Windows-gnu-i686',
        'i686-pc-windows-gnullvm'             => 'Windows-gnullvm-i686',
        'i686-pc-windows-msvc'                => 'Windows-msvc-i686',
        'i686-unknown-freebsd'                => 'FreeBSD-i686',
        'i686-unknown-linux-gnu'              => 'Linux-gnu-i686',
        'i686-unknown-linux-musl'             => 'Linux-musl-i686',
        'loongarch64-unknown-linux-gnu'       => 'Linux-gnu-loongarch64',
        'powerpc-unknown-linux-gnu'           => 'Linux-gnu-powerpc',
        'powerpc64-unknown-linux-gnu'         => 'Linux-gnu-powerpc64',
        'powerpc64le-unknown-linux-gnu'       => 'Linux-gnu-powerpc64le',
        'riscv64gc-unknown-linux-gnu'         => 'Linux-gnu-riscv64gc',
        's390x-unknown-linux-gnu'             => 'Linux-gnu-s390x',
        'sparc64-unknown-linux-gnu'           => 'Linux-gnu-sparc64',
        'sparcv9-sun-solaris'                 => 'Solaris-sparcv9',
        'thumbv7neon-linux-androideabi'       => 'Linux-androideabi-thumbv7neon',
        'thumbv7neon-unknown-linux-gnueabihf' => 'Linux-gnueabihf-thumbv7neon',
        'x86_64-apple-darwin'                 => 'macOS-x86_64',
        'x86_64-apple-ios'                    => 'iOS-x86_64',
        'x86_64-linux-android'                => 'Linux-android-x86_64',
        'x86_64-pc-solaris'                   => 'Solaris-x86_64',
        'x86_64-pc-windows-gnu'               => 'Windows-gnu-x86_64',
        'x86_64-pc-windows-gnullvm'           => 'Windows-gnullvm-x86_64',
        'x86_64-pc-windows-msvc'              => 'Windows-msvc-x86_64',
        'x86_64-unknown-freebsd'              => 'FreeBSD-x86_64',
        'x86_64-unknown-fuchsia'              => 'Fuchsia-x86_64',
        'x86_64-unknown-illumos'              => 'Illumos-x86_64',
        'x86_64-unknown-linux-gnu'            => 'Linux-gnu-x86_64',
        'x86_64-unknown-linux-gnux32'         => 'Linux-gnux32-x86_64',
        'x86_64-unknown-linux-musl'           => 'Linux-musl-x86_64',
        'x86_64-unknown-linux-ohos'           => 'Linux-ohos-x86_64',
        'x86_64-unknown-netbsd'               => 'NetBSD-x86_64',
        'x86_64-unknown-redox'                => 'Redox-x86_64',
    );

    for my $target ( keys %tests ) {
        is(
            target_to_archive_name($target),
            $tests{$target},
            "$target == $tests{$target}",
        );
    }

    done_testing();
}

if ( $ENV{TAP_VERSION} ) {
    test();
}
else {
    main();
}
