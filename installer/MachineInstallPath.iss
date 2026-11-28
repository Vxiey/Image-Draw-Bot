// This installer never grants additional file permissions. For an all-users
// update, verify the existing installation before Inno writes into it.
type
  TAccessEntry = record
    Kind, Flags: Byte;
    Size: Word;
    Mask: Cardinal;
  end;
  TAclSize = record
    Count, Used, Free: Cardinal;
  end;

function MachineFileAttributes(const Name: String): Cardinal;
  external 'GetFileAttributesW@kernel32.dll stdcall';
function MachineSecurity(const Name: String; Kind, Info: Cardinal;
  var Owner: THandle; Group: THandle; var Dacl: THandle; Sacl: THandle;
  var Descriptor: THandle): Cardinal;
  external 'GetNamedSecurityInfoW@advapi32.dll stdcall';
function MachineAclSize(Acl: THandle; var Info: TAclSize; Size, Kind: Cardinal): BOOL;
  external 'GetAclInformation@advapi32.dll stdcall';
function MachineAce(Acl: THandle; Index: Cardinal; var Ace: THandle): BOOL;
  external 'GetAce@advapi32.dll stdcall';
procedure ReadMachineAce(var Entry: TAccessEntry; Addr, Size: THandle);
  external 'RtlMoveMemory@kernel32.dll stdcall';
function MachineWellKnownSid(Sid: THandle; Kind: Cardinal): BOOL;
  external 'IsWellKnownSid@advapi32.dll stdcall';
function MachineEqualSid(First, Second: THandle): BOOL;
  external 'EqualSid@advapi32.dll stdcall';
function MachineMakeSid(const Text: String; var Sid: THandle): BOOL;
  external 'ConvertStringSidToSidW@advapi32.dll stdcall';
function MachineLocalFree(Address: THandle): THandle;
  external 'LocalFree@kernel32.dll stdcall';

function TrustedMachinePrincipal(Sid, TrustedInstaller: THandle): Boolean;
begin
  { WinLocalSystemSid, WinBuiltinAdministratorsSid, TrustedInstaller }
  Result := (Sid <> 0) and (MachineWellKnownSid(Sid, 22) or
    MachineWellKnownSid(Sid, 26) or MachineEqualSid(Sid, TrustedInstaller));
end;

function ProtectedMachineAccess(const Name: String; TrustedInstaller: THandle): Boolean;
var
  Owner, Dacl, Descriptor, Ace, Sid: THandle;
  Acl: TAclSize;
  Index: Cardinal;
  Entry: TAccessEntry;
begin
  Result := False;
  { SE_FILE_OBJECT, OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION }
  if MachineSecurity(Name, 1, 5, Owner, 0, Dacl, 0, Descriptor) <> 0 then Exit;
  try
    if (Dacl = 0) or not TrustedMachinePrincipal(Owner, TrustedInstaller) then Exit;
    if not MachineAclSize(Dacl, Acl, SizeOf(Acl), 2) then Exit;
    Index := 0;
    while Index < Acl.Count do begin
      if not MachineAce(Dacl, Index, Ace) then Exit;
      { Read only ACE_HEADER until the native ACE is known to contain a mask and SID. }
      ReadMachineAce(Entry, Ace, 4);
      if (Entry.Kind > 1) or (Entry.Size < 16) then Exit;
      if Entry.Kind = 0 then begin
        ReadMachineAce(Entry, Ace, SizeOf(Entry));
        { FILE_GENERIC_READ | FILE_GENERIC_EXECUTE and their generic forms. }
        if (Entry.Mask and $5FEDFF56) <> 0 then begin
          Sid := Ace + SizeOf(Entry);
          if not TrustedMachinePrincipal(Sid, TrustedInstaller) then
            if not (((Entry.Flags and $08) <> 0) and MachineWellKnownSid(Sid, 3)) then Exit;
          { The inherit-only CREATOR OWNER template takes effect on a child's }
          { actual owner, which we verify independently on each existing item. }
        end;
      end;
      Index := Index + 1;
    end;
    Result := True;
  finally
    MachineLocalFree(Descriptor);
  end;
end;

function ProtectedMachineTree(const Name: String; Attributes: Cardinal;
  TrustedInstaller: THandle; Depth: Integer; var Remaining: Integer): Boolean;
var
  Item: TFindRec;
begin
  Result := False;
  Remaining := Remaining - 1;
  if (Remaining < 0) or (Depth > 64) or ((Attributes and FILE_ATTRIBUTE_REPARSE_POINT) <> 0) then Exit;
  if not ProtectedMachineAccess(Name, TrustedInstaller) then Exit;
  if (Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then begin
    if not FindFirst(AddBackslash(Name) + '*', Item) then Exit;
    try
      repeat
        if (Item.Name <> '.') and (Item.Name <> '..') then
          if not ProtectedMachineTree(AddBackslash(Name) + Item.Name, Item.Attributes,
            TrustedInstaller, Depth + 1, Remaining) then Exit;
      until not FindNext(Item);
    finally
      FindClose(Item);
    end;
  end;
  Result := True;
end;

function SafeMachineDestination(const Name: String): Boolean;
const
  MissingFile = 2;
  TrustedInstallerSid = 'S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464';
var
  Root, Expected: String;
  Attributes: Cardinal;
  TrustedInstaller: THandle;
  Remaining: Integer;
begin
  Result := False;
  Root := ExpandConstant('{commonpf}');
  Expected := AddBackslash(Root) + 'Image Draw Bot';
  if CompareText(RemoveBackslashUnlessRoot(Name), Expected) <> 0 then Exit;
  if not MachineMakeSid(TrustedInstallerSid, TrustedInstaller) then Exit;
  try
    Attributes := MachineFileAttributes(Root);
    if (Attributes = $FFFFFFFF) or ((Attributes and FILE_ATTRIBUTE_DIRECTORY) = 0) or
      ((Attributes and FILE_ATTRIBUTE_REPARSE_POINT) <> 0) or not ProtectedMachineAccess(Root, TrustedInstaller) then Exit;
    Attributes := MachineFileAttributes(Expected);
    if Attributes = $FFFFFFFF then begin
      Result := DLLGetLastError = MissingFile;
      Exit;
    end;
    if (Attributes and FILE_ATTRIBUTE_DIRECTORY) = 0 then Exit;
    Remaining := 100000;
    Result := ProtectedMachineTree(Expected, Attributes, TrustedInstaller, 0, Remaining);
  finally
    MachineLocalFree(TrustedInstaller);
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if IsAdminInstallMode then
    if not SafeMachineDestination(WizardDirValue) then begin
      Result := 'All-users installation requires the protected folder ' +
        ExpandConstant('{commonpf}\Image Draw Bot') + '. Choose that folder in Setup or select ' +
        'Install for me only for a custom location. Ask an administrator to review any existing files there.';
      Log(Result);
    end;
end;
