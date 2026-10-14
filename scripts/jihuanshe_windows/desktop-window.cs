using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;

namespace KamiJhs {
 public sealed class WindowInfo {
  public long Handle {get;set;}
  public int ProcessId {get;set;}
  public string DesktopId {get;set;}
  public int DesktopNumber {get;set;}
  public bool Pinned {get;set;}
 }
 public sealed class RecoveryResult {
  public bool Placed {get;set;}
  public bool DesktopUnchanged {get;set;}
  public bool ForegroundUnchanged {get;set;}
  public int FocusEvents {get;set;}
  public int Moves {get;set;}
 }
 public static class Desktop {
  [UnmanagedFunctionPointer(CallingConvention.Cdecl)] delegate int NoArgs();
  [UnmanagedFunctionPointer(CallingConvention.Cdecl)] delegate Guid IndexGuid(int index);
  [UnmanagedFunctionPointer(CallingConvention.Cdecl)] delegate int GuidIndex(Guid id);
  [UnmanagedFunctionPointer(CallingConvention.Cdecl)] delegate Guid WindowGuid(IntPtr h);
  [UnmanagedFunctionPointer(CallingConvention.Cdecl)] delegate int WindowInt(IntPtr h);
  [UnmanagedFunctionPointer(CallingConvention.Cdecl)] delegate int MoveWindow(IntPtr h,int index);
  static NoArgs current,count;
  static IndexGuid desktopId;
  static GuidIndex desktopIndex;
  static WindowGuid windowId;
  static WindowInt pinnedWindow,pinnedApp;
  static MoveWindow move;
  static IntPtr library;
  delegate bool EnumCallback(IntPtr h,IntPtr p);
  delegate void EventCallback(IntPtr hook,uint ev,IntPtr h,int obj,int child,uint thread,uint time);
  [StructLayout(LayoutKind.Sequential)] struct LASTINPUTINFO {public uint size,time;}
  [DllImport("user32.dll")] static extern bool GetLastInputInfo(ref LASTINPUTINFO info);
  static uint LastInput(){var info=new LASTINPUTINFO{size=(uint)Marshal.SizeOf<LASTINPUTINFO>()};return GetLastInputInfo(ref info)?info.time:uint.MaxValue;}
  static bool IsWeChatWindow(IntPtr h){uint pid;GetWindowThreadProcessId(h,out pid);try{string n=Process.GetProcessById((int)pid).ProcessName;return n=="WeChatAppEx"||n=="Weixin"||n=="WeChat";}catch{return false;}}
  [StructLayout(LayoutKind.Sequential)] struct POINT {public int x,y;}
  [StructLayout(LayoutKind.Sequential)] struct MSG {public IntPtr h;public uint message;public UIntPtr w;public IntPtr l;public uint time;public POINT point;public uint privateData;}
  [DllImport("user32.dll")] static extern bool EnumWindows(EnumCallback fn,IntPtr param);
  [DllImport("user32.dll",CharSet=CharSet.Unicode)] static extern int GetWindowText(IntPtr h,StringBuilder s,int length);
  [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h,out uint pid);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] static extern bool IsWindow(IntPtr h);
  [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] static extern IntPtr GetAncestor(IntPtr h,uint flags);
  [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr h,int command);
  [DllImport("user32.dll")] static extern bool PostMessage(IntPtr h,uint message,IntPtr w,IntPtr l);
  [DllImport("user32.dll")] static extern IntPtr SetWinEventHook(uint min,uint max,IntPtr module,EventCallback fn,uint pid,uint tid,uint flags);
  [DllImport("user32.dll")] static extern bool UnhookWinEvent(IntPtr h);
  [DllImport("user32.dll")] static extern bool PeekMessage(out MSG msg,IntPtr h,uint min,uint max,uint remove);
  [DllImport("user32.dll")] static extern bool TranslateMessage(ref MSG msg);
  [DllImport("user32.dll")] static extern IntPtr DispatchMessage(ref MSG msg);
  static T Export<T>(string name) where T:Delegate {return Marshal.GetDelegateForFunctionPointer<T>(NativeLibrary.GetExport(library,name));}
  public static void Load(string file) {
   if(library!=IntPtr.Zero)return;
   library=NativeLibrary.Load(Path.GetFullPath(file));
   current=Export<NoArgs>("GetCurrentDesktopNumber");count=Export<NoArgs>("GetDesktopCount");
   desktopId=Export<IndexGuid>("GetDesktopIdByNumber");desktopIndex=Export<GuidIndex>("GetDesktopNumberById");
   windowId=Export<WindowGuid>("GetWindowDesktopId");move=Export<MoveWindow>("MoveWindowToDesktopNumber");
   pinnedWindow=Export<WindowInt>("IsPinnedWindow");pinnedApp=Export<WindowInt>("IsPinnedApp");
   if(current()<0||count()<1)throw new Exception("desktop_api_unavailable");
  }
  public static int CurrentNumber(){return current();}
  public static int Count(){return count();}
  public static Guid IdAt(int index){return desktopId(index);}
  public static int IndexOf(Guid id){return desktopIndex(id);}
  static bool IsMiniapp(IntPtr h) {
   if(h==IntPtr.Zero||GetAncestor(h,2)!=h)return false;
   var title=new StringBuilder(512);GetWindowText(h,title,title.Capacity);
   if(!title.ToString().StartsWith("\u96c6\u6362\u793e",StringComparison.Ordinal))return false;
   uint pid;GetWindowThreadProcessId(h,out pid);
   try{string name=Process.GetProcessById((int)pid).ProcessName;return name=="WeChatAppEx"||name=="Weixin";}catch{return false;}
  }
  static IntPtr[] Windows(bool visibleOnly) {
   var found=new List<IntPtr>();
   EnumWindows((h,p)=>{if(IsMiniapp(h)&&(!visibleOnly||IsWindowVisible(h)))found.Add(h);return true;},IntPtr.Zero);
   return found.ToArray();
  }
  public static WindowInfo[] Inspect(bool includeHidden=false) {
   var result=new List<WindowInfo>();
   foreach(var h in Windows(!includeHidden)) {
    uint pid;GetWindowThreadProcessId(h,out pid);Guid id=windowId(h);
    result.Add(new WindowInfo{Handle=h.ToInt64(),ProcessId=(int)pid,DesktopId=id.ToString(),DesktopNumber=desktopIndex(id)+1,Pinned=pinnedWindow(h)!=0||pinnedApp(h)!=0});
   }
   return result.ToArray();
  }
  static void Pump(){MSG msg;while(PeekMessage(out msg,IntPtr.Zero,0,0,1)){TranslateMessage(ref msg);DispatchMessage(ref msg);}}
  public static RecoveryResult Recover(Guid target,string shortcut,bool launchOnly) {
   if(target==Guid.Empty||desktopIndex(target)<0)throw new Exception("desktop_missing");
   if(!File.Exists(shortcut))throw new Exception("shortcut_missing");
   if(Process.GetProcessesByName("Weixin").Length==0&&Process.GetProcessesByName("WeChat").Length==0)throw new Exception("wechat_unavailable");
   foreach(var h in Windows(true))if(pinnedWindow(h)!=0||pinnedApp(h)!=0)throw new Exception("miniapp_pinned");
   Guid originalDesktop=desktopId(current());IntPtr originalForeground=GetForegroundWindow();
   if(originalDesktop==Guid.Empty)throw new Exception("desktop_api_unavailable");
   var result=new RecoveryResult();bool failed=false;var hidden=new HashSet<IntPtr>();
   uint inputBefore=LastInput();var seenFocus=new HashSet<IntPtr>();
   Action restoreFocus=()=>{
    IntPtr active=GetForegroundWindow();
    if(active!=originalForeground&&IsWeChatWindow(active)&&inputBefore!=uint.MaxValue&&LastInput()==inputBefore&&IsWindow(originalForeground)&&desktopId(current())==originalDesktop){
     if(seenFocus.Add(active))result.FocusEvents++;
     SetForegroundWindow(originalForeground);
    }
   };
   Action<IntPtr> route=h=>{
    if(!IsMiniapp(h))return;
    restoreFocus();
    if(windowId(h)==target){if(hidden.Remove(h))ShowWindow(h,4);return;}
    int index=desktopIndex(target);if(index<0){failed=true;return;}
    bool visible=IsWindowVisible(h)||hidden.Contains(h);
    bool placed=move(h,index)>0&&windowId(h)==target;
    if(!placed){if(IsWindowVisible(h)){hidden.Add(h);ShowWindow(h,0);}return;}
    result.Moves++;
    hidden.Remove(h);if(visible)ShowWindow(h,4);
   };
   EventCallback callback=(hook,ev,h,obj,child,thread,time)=>{if(obj==0&&child==0){try{if(ev==3)restoreFocus();route(h);}catch{failed=true;}}};
   IntPtr objectHook=SetWinEventHook(0x8000,0x800C,IntPtr.Zero,callback,0,0,0);
   IntPtr focusHook=SetWinEventHook(3,3,IntPtr.Zero,callback,0,0,0);
   if(objectHook==IntPtr.Zero||focusHook==IntPtr.Zero){if(objectHook!=IntPtr.Zero)UnhookWinEvent(objectHook);if(focusHook!=IntPtr.Zero)UnhookWinEvent(focusHook);throw new Exception("window_watch_unavailable");}
   try {
    if(!launchOnly) {
     foreach(var h in Windows(true))PostMessage(h,0x0010,IntPtr.Zero,IntPtr.Zero);
     var closeWatch=Stopwatch.StartNew();
     while(Windows(true).Length>0&&closeWatch.ElapsedMilliseconds<2500){Pump();Thread.Sleep(25);}
     if(Windows(true).Length>0)throw new Exception("miniapp_close_failed");
    }
    if(desktopIndex(target)<0)throw new Exception("desktop_missing");
    Process.Start(new ProcessStartInfo(shortcut){UseShellExecute=true,WindowStyle=ProcessWindowStyle.Hidden});
    var watch=Stopwatch.StartNew();long settled=-1;
    while(watch.ElapsedMilliseconds<18000) {
     Pump();restoreFocus();foreach(var h in Windows(false))route(h);
     if(failed)throw new Exception("desktop_placement_failed");
     var windows=Windows(true);bool placed=windows.Length>0;
     foreach(var h in windows)if(windowId(h)!=target)placed=false;
     if(placed){if(settled<0)settled=watch.ElapsedMilliseconds;}else settled=-1;
     if(settled>=0&&watch.ElapsedMilliseconds-settled>=3000&&watch.ElapsedMilliseconds>=8000){result.Placed=true;break;}
     Thread.Sleep(25);
    }
    result.DesktopUnchanged=desktopId(current())==originalDesktop;
    result.ForegroundUnchanged=GetForegroundWindow()==originalForeground;
    if(!result.Placed)throw new Exception("miniapp_window_timeout");
    return result;
   } catch {foreach(var h in Windows(false)){if(hidden.Contains(h)||windowId(h)!=target)PostMessage(h,0x0010,IntPtr.Zero,IntPtr.Zero);}throw;} finally {UnhookWinEvent(objectHook);UnhookWinEvent(focusHook);GC.KeepAlive(callback);}
  }
 }
}