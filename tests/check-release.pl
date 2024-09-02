#!/usr/bin/env perl

use v5.30;
use strict;
use warnings;
no warnings 'experimental::signatures';
use feature 'signatures';

use FindBin qw( $Bin );
use File::Spec;
use lib File::Spec->catdir( $Bin, 'lib' );

use autodie qw( :all );

use Digest::SHA;
use File::Temp qw( tempdir );
use Getopt::Long;
use IPC::System::Simple qw( capturex );
use Test::More;

sub main {
    my $artifact_id;
    my $executable_name;
    my $github_token;
    my $repo;
    my $target;

    GetOptions(
        'artifact-id=s'     => \$artifact_id,
        'executable-name=s' => \$executable_name,
        'github-token=s'    => \$github_token,
        'repo=s'            => \$repo,
        'target=s'          => \$target,
    );

    # We want to run this in a clean dir to avoid any conflicts with files in the current dir, like
    # the archive file containing the release.
    my $td = tempdir();
    chdir $td;

    system(
        'curl',
        '-L',
        '-H', 'Accept: application/vnd.github+json',
        '-H', "Authorization: Bearer $github_token",
        '-o', 'artifact.zip',
        "https://api.github.com/repos/$repo/actions/artifacts/$artifact_id/zip",
    );

    system( 'unzip', 'artifact.zip' );

    my $glob  = $target =~ /windows/i ? 'test-project*.zip*' : 'test-project*.tar.gz*';
    my @files = glob $glob;

    is( scalar @files, 2, 'found two files in the artifact tarball' )
        or diag("@files");
    my ($archive_file)  = grep { !/sha256/ } @files;
    my ($checksum_file) = grep {/sha256/} @files;

    ok( $archive_file,  'found an archive file in the artifact tarball' );
    ok( $checksum_file, 'found a checksum file in the artifact tarball' );

    open my $fh, '<', $checksum_file;
    my $sha256_contents = do { local $/; <$fh> };
    $sha256_contents =~ s/^\s+|\s+$//g;
    my ( $checksum, $filename ) = $sha256_contents =~ /^(\S+) [ \*](\S+)$/;
    is( $filename, $archive_file, 'filename in checksum file matches archive filename' )
        or diag($sha256_contents);

    # I would prefer to just run shasum but I wasn't able to get it to run on Windows.
    my $sha = Digest::SHA->new(256);
    $sha->addfile($filename);
    is( $checksum, $sha->hexdigest, 'checksum in checksum file is correct' );

    if ( $archive_file =~ /\.zip$/ ) {
        system( 'unzip', $archive_file );
    }
    else {
        system( 'tar', 'xzf', $archive_file );
    }

    for my $file ( $executable_name, qw( README.md Changes.md ) ) {
        ok( -f $file, "$file exists after unpacking archive" );
    }

    done_testing();
}

main();
