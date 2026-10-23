param([ValidateSet('Setup','Run','Status','Stop','SelfTest')][string]$Mode='Setup')
$ErrorActionPreference='Stop'
$Root=Join-Path $env:LOCALAPPDATA 'AutoDartGongsi'
$TaskName='AutoDartGongsi_5min'
function Kst { [TimeZoneInfo]::ConvertTimeBySystemTimeZoneId([DateTime]::UtcNow,'Korea Standard Time') }
function Save-State($State) {
    $path=Join-Path $Root 'state.json'
    [IO.File]::WriteAllText(($path+'.tmp'),($State|ConvertTo-Json -Depth 8),(New-Object Text.UTF8Encoding($true)))
    Move-Item -LiteralPath ($path+'.tmp') -Destination $path -Force
}
function Log($Text) { Add-Content -LiteralPath (Join-Path $Root 'monitor.log') -Encoding UTF8 -Value ((Kst).ToString('yyyy-MM-dd HH:mm:ss')+' '+$Text) }
function Reveal($Secret) { ([Net.NetworkCredential]::new('',$Secret)).Password }
function Tg($Method,$Body) {
    try {
        $uri='https://api.telegram.org/bot'+(Reveal $script:BotToken)+'/'+$Method
        $payload=[Text.Encoding]::UTF8.GetBytes(($Body|ConvertTo-Json -Depth 8 -Compress))
        $r=Invoke-RestMethod -Uri $uri -Method Post -ContentType 'application/json; charset=utf-8' -Body $payload -TimeoutSec 25
        if (!$r.ok) { throw '응답 오류' }
        $r.result
    } catch { throw "Telegram $Method 실패. 토큰, 네트워크, 전송 권한을 확인하세요." }
}
function DartPage($Start,$End,$Page) {
    try {
        $key=[Uri]::EscapeDataString((Reveal $script:DartKey))
        $uri="https://opendart.fss.or.kr/api/list.json?crtfc_key=$key&bgn_de=$Start&end_de=$End&last_reprt_at=N&sort=date&sort_mth=desc&page_count=100&page_no=$Page"
        $r=Invoke-RestMethod -Uri $uri -TimeoutSec 25
    } catch { throw 'OpenDART 연결 실패. 네트워크를 확인하세요.' }
    if ($r.status -eq '013') { return [pscustomobject]@{total_page=0;list=@()} }
    if ($r.status -ne '000') { throw ('OpenDART 오류 코드 '+$r.status+'. 인증키 또는 이용 제한을 확인하세요.') }
    $r
}
function Target($Report,$Titles) {
    $name=([regex]::Replace([string]$Report.report_nm,'^(\[[^\]]+\]\s*)+','')).Trim()
    $Titles -contains $name
}
function Reports($Start,$End,$Titles) {
    $first=DartPage $Start $End 1
    if ([int]$first.total_page -gt 300) { throw '조회 범위가 너무 큽니다. 기간을 나눠 복구해야 합니다.' }
    $found=New-Object 'System.Collections.Generic.Dictionary[string,object]'
    for ($p=1;$p -le [int]$first.total_page;$p++) {
        if ($p -eq 1) { $data=$first } else { $data=DartPage $Start $End $p }
        foreach ($report in @($data.list)) {
            if (Target $report $Titles) { $found[[string]$report.rcept_no]=$report }
        }
    }
    @($found.Values|Sort-Object rcept_dt,rcept_no)
}
function Alert($Report,$Prefix='') {
    $nl=[Environment]::NewLine
    $Prefix+'['+$Report.corp_name+'] '+$Report.report_nm+$nl+'접수일: '+$Report.rcept_dt+$nl+'접수번호: '+$Report.rcept_no+$nl+'https://dart.fss.or.kr/dsaf001/main.do?rcpNo='+$Report.rcept_no
}
function Send($Text) {
    $r=Tg 'sendMessage' @{chat_id='6766930417';text=$Text;link_preview_options=@{is_disabled=$true}}
    if ([string]$r.chat.id -ne '6766930417') { throw '수신 채팅 검증 실패' }
}
function Poll {
    $started=Kst
    $state=Get-Content -LiteralPath (Join-Path $Root 'state.json') -Raw -Encoding UTF8|ConvertFrom-Json
    if ($state.last_success -is [DateTime]) { $last=$state.last_success } else { $last=[DateTime]::ParseExact([string]$state.last_success,'yyyy-MM-ddTHH:mm:ss',[Globalization.CultureInfo]::InvariantCulture) }
    if (($started-$last).TotalDays -gt 85) { throw '85일 이상 중단되었습니다. 별도 복구가 필요합니다.' }
    $reports=@(Reports $last.ToString('yyyyMMdd') $started.ToString('yyyyMMdd') @($script:Config.report_titles))
    $seen=New-Object 'System.Collections.Generic.HashSet[string]'
    foreach ($id in @($state.seen)) { if ($id) { [void]$seen.Add([string]$id) } }
    $count=0
    foreach ($report in $reports) {
        $id=[string]$report.rcept_no
        if ($seen.Contains($id)) { continue }
        Send (Alert $report)
        [void]$seen.Add($id)
        $state.seen=@($seen)
        Save-State $state
        $count++
        Start-Sleep -Milliseconds 1100
    }
    $state.last_success=$started.ToString('yyyy-MM-ddTHH:mm:ss')
    Save-State $state
    Log "OK 신규전송=$count 조회대상=$($reports.Count)"
    Write-Host "조회 완료: 신규 $count 건"
}
if ($Mode -eq 'SelfTest') {
    $report=[pscustomobject]@{report_nm='[기재정정]증권발행실적보고서';corp_name='테스트';rcept_no='20261023000149';rcept_dt='20261023'}
    if (!(Target $report @('증권발행실적보고서'))) { throw '정정 필터 실패' }
    if (Target ([pscustomobject]@{report_nm='증권발행실적보고서(집합투자증권)'}) @('증권발행실적보고서')) { throw '정확 일치 필터 실패' }
    if (!(Alert $report).Contains('rcpNo=20261023000149')) { throw '원문 링크 실패' }
    $script:testState=[pscustomobject]@{last_success=(Kst).ToString('yyyy-MM-ddTHH:mm:ss');seen=@('old')}
    $script:Config=[pscustomobject]@{report_titles=@('증권발행실적보고서')}
    $script:sentCount=0
    $script:failSend=$false
    $script:saved=$false
    function Get-Content { $script:testState|ConvertTo-Json }
    function Reports { @([pscustomobject]@{rcept_no='old'},[pscustomobject]@{rcept_no='new'}) }
    function Send { if ($script:failSend) { throw 'simulated send failure' }; $script:sentCount++ }
    function Save-State($State) { $script:saved=$true }
    function Log {}
    Poll
    if ($script:sentCount -ne 1 -or !$script:saved) { throw '중복방지 또는 저장 실패' }
    $script:failSend=$true
    $script:saved=$false
    $script:testState=[pscustomobject]@{last_success=(Kst).ToString('yyyy-MM-ddTHH:mm:ss');seen=@('old')}
    $failed=$false
    try { Poll } catch { $failed=$true }
    if (!$failed -or $script:saved) { throw '실패 전송 보존 실패' }
    Write-Host 'SELFTEST OK: report filtering, links, deduplication, failed-send preservation'
    exit
}
if ($Mode -eq 'Stop') {
    $task=Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($task) { Disable-ScheduledTask -TaskName $TaskName|Out-Null }
    Write-Host '예약 실행 중지 완료';exit
}
if ($Mode -eq 'Status') {
    Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue|Select-Object TaskName,State
    if (Test-Path -LiteralPath (Join-Path $Root 'monitor.log')) { Get-Content -LiteralPath (Join-Path $Root 'monitor.log') -Tail 10 -Encoding UTF8 }
    exit
}
$lock=$null
try {
    if ($Mode -eq 'Setup') {
        Write-Host '5분 간격으로 전체 기업의 지정 보고서를 확인합니다. PC가 켜져 있고 로그인한 동안 실행됩니다.'
        Write-Host '키는 현재 Windows 사용자 계정으로 암호화하여 이 PC에 저장됩니다.'
        $script:BotToken=Read-Host 'Telegram 봇 토큰 (입력 숨김)' -AsSecureString
        $script:DartKey=Read-Host 'OpenDART 인증키 (입력 숨김)' -AsSecureString
        $me=Tg 'getMe' @{}
        if ($me.username -ne 'auto_dart_gongsi_bot') { throw '지정한 봇의 토큰이 아닙니다.' }
        $chat=Tg 'getChat' @{chat_id='6766930417'}
        if ([string]$chat.id -ne '6766930417' -or $chat.type -ne 'private') { throw '수신 대화방 불일치' }
        $inputTitles=Read-Host '보고서명 (여러 개는 세미콜론, Enter=증권발행실적보고서)'
        if ([string]::IsNullOrWhiteSpace($inputTitles)) { $titles=@('증권발행실적보고서') }
        else { $titles=@($inputTitles.Split(';')|ForEach-Object {$_.Trim()}|Where-Object {$_}) }
        $started=Kst
        $today=$started.ToString('yyyyMMdd')
        $reports=@(Reports $today $today $titles)
        Write-Host "다트 조회 성공: 오늘 대상 $($reports.Count) 건"
        $existing=Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if ($existing -and ($existing.Actions.Arguments -notlike '*AutoDartGongsi*')) { throw '동일한 이름의 다른 예약 작업이 있습니다.' }
        [void][IO.Directory]::CreateDirectory($Root)
        $lock=[IO.File]::Open((Join-Path $Root 'monitor.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
        $destination=Join-Path $Root 'dart_alert.ps1'
        if ([IO.Path]::GetFullPath($PSCommandPath) -ne [IO.Path]::GetFullPath($destination)) { Copy-Item -LiteralPath $PSCommandPath -Destination $destination -Force }
        [pscustomobject]@{bot_token=$script:BotToken;dart_key=$script:DartKey;report_titles=$titles}|
            Export-Clixml -LiteralPath (Join-Path $Root 'credentials.xml') -Encoding UTF8
        if (!(Test-Path -LiteralPath (Join-Path $Root 'state.json'))) {
            Save-State ([pscustomobject]@{last_success=$started.ToString('yyyy-MM-ddTHH:mm:ss');seen=@($reports|ForEach-Object {[string]$_.rcept_no})})
        }
        $nl=[Environment]::NewLine
        Send ('다트 조회 연결 성공'+$nl+'대상: 전체 기업 / '+($titles -join ', ')+$nl+"오늘 조회: $($reports.Count)건"+$nl+'기존 공시는 기준으로 저장합니다. 5분 간격 예약 실행을 설정합니다.')
        if ($reports.Count) { Send (Alert $reports[-1] ('[연결 테스트 / 기존 공시]'+$nl)) }
        $exe=(Get-Process -Id $PID).Path
        $action=New-ScheduledTaskAction -Execute $exe -Argument ('-NoProfile -NonInteractive -WindowStyle Hidden -File "'+$destination+'" -Mode Run')
        $trigger=New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
        $userId=[Security.Principal.WindowsIdentity]::GetCurrent().Name
        $principal=New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited
        $settings=New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 4)
        $task=New-ScheduledTask -Action $action -Trigger $trigger -Principal $principal -Settings $settings
        Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force|Out-Null
        Log 'SETUP OK 예약 등록 완료'
        Write-Host 'SETUP SUCCESS: AutoDartGongsi_5min 예약 등록 완료' -ForegroundColor Green
        Write-Host ('상태: & "'+$destination+'" -Mode Status')
        Write-Host ('중지: & "'+$destination+'" -Mode Stop')
    } else {
        $script:Config=Import-Clixml -LiteralPath (Join-Path $Root 'credentials.xml')
        $script:BotToken=$script:Config.bot_token
        $script:DartKey=$script:Config.dart_key
        $lock=[IO.File]::Open((Join-Path $Root 'monitor.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
        Poll
    }
} catch {
    $safe=$_.Exception.Message
    $safe=$safe -replace 'https://\S+','[URL 숨김]'
    Write-Host ("$Mode FAILED: "+$safe) -ForegroundColor Red
    if (Test-Path -LiteralPath $Root) { Log ('ERROR '+$safe) }
    exit 1
} finally {
    if ($lock) { $lock.Dispose() }
    if ($script:BotToken) { $script:BotToken.Dispose() }
    if ($script:DartKey) { $script:DartKey.Dispose() }
}
