#!/usr/bin/env python3
"""
一次性音量检查脚本
功能：如果系统音量 > 90%，则设置为 20%
使用ctypes直接调用CoreAudio原生API实现高性能

性能预期：
- get_volume(): ~0.01-0.1ms
- set_volume(): ~0.1-1ms
- 1秒内可执行: 1000+ 次
"""

import ctypes
from ctypes import POINTER, c_uint32, c_float, c_bool, Structure, byref, c_void_p
import sys
import time

print("[DEBUG] 加载CoreAudio框架...")
coreaudio = ctypes.CDLL(
    '/System/Library/Frameworks/CoreAudio.framework/Versions/A/CoreAudio'
)
print("[DEBUG] CoreAudio加载成功")

# ============ 常量定义 ============
kAudioObjectSystemObject = 1
kAudioObjectPropertyElementMain = 0  # vmvc属性需要用0
kAudioObjectPropertyElementMaster = 0

# FourCC codes
kAudioHardwarePropertyDefaultOutputDevice = int.from_bytes(b'dOut', byteorder='big')  # 默认输出设备
kAudioHardwareServiceDeviceProperty_VirtualMainVolume = int.from_bytes(b'vmvc', byteorder='big')  # 虚拟主音量
kAudioDevicePropertyScopeOutput = int.from_bytes(b'outp', byteorder='big')  # 输出范围

kAudioHardwareNoError = 0

print(f"[DEBUG] 常量初始化完成:")
print(f"  - kAudioObjectSystemObject: {kAudioObjectSystemObject}")
print(f"  - kAudioHardwarePropertyDefaultOutputDevice: {kAudioHardwarePropertyDefaultOutputDevice}")
print(f"  - kAudioHardwareServiceDeviceProperty_VirtualMainVolume: {kAudioHardwareServiceDeviceProperty_VirtualMainVolume}")
print(f"  - kAudioDevicePropertyScopeOutput: {kAudioDevicePropertyScopeOutput}")

# ============ 结构体定义 ============
class AudioObjectPropertyAddress(Structure):
    _fields_ = [
        ("mSelector", c_uint32),
        ("mScope", c_uint32),
        ("mElement", c_uint32),
    ]

# ============ 函数签名设置 ============
coreaudio.AudioObjectGetPropertyData.argtypes = [
    c_uint32, POINTER(AudioObjectPropertyAddress), c_uint32, c_void_p, POINTER(c_uint32), c_void_p
]
coreaudio.AudioObjectGetPropertyData.restype = c_uint32

coreaudio.AudioObjectSetPropertyData.argtypes = [
    c_uint32, POINTER(AudioObjectPropertyAddress), c_uint32, c_void_p, c_uint32, c_void_p
]
coreaudio.AudioObjectSetPropertyData.restype = c_uint32

coreaudio.AudioObjectHasProperty.argtypes = [c_uint32, POINTER(AudioObjectPropertyAddress)]
coreaudio.AudioObjectHasProperty.restype = c_bool

coreaudio.AudioObjectIsPropertySettable.argtypes = [c_uint32, POINTER(AudioObjectPropertyAddress), POINTER(c_bool)]
coreaudio.AudioObjectIsPropertySettable.restype = c_uint32

print("[DEBUG] 函数签名设置完成")

# ============ 核心函数 ============

def get_default_output_device():
    """获取默认输出设备ID"""
    print("\n[DEBUG] 获取默认输出设备ID...")
    
    addr = AudioObjectPropertyAddress(
        mSelector=kAudioHardwarePropertyDefaultOutputDevice,
        mScope=0,
        mElement=0
    )
    
    device_id = c_uint32(0)
    data_size = c_uint32(ctypes.sizeof(device_id))
    
    start_time = time.perf_counter()
    result = coreaudio.AudioObjectGetPropertyData(
        kAudioObjectSystemObject, byref(addr), 0, None, byref(data_size), byref(device_id)
    )
    elapsed = (time.perf_counter() - start_time) * 1000
    
    if result != kAudioHardwareNoError:
        raise RuntimeError(f"获取输出设备失败: {result}")
    
    print(f"[DEBUG] 获取设备ID完成，设备ID: {device_id.value}，耗时: {elapsed:.4f}ms")
    return device_id.value


def get_volume(device_id):
    """获取音量 (返回0.0-1.0)"""
    print(f"[DEBUG] 读取设备 {device_id} 的音量...")
    
    addr = AudioObjectPropertyAddress(
        mSelector=kAudioHardwareServiceDeviceProperty_VirtualMainVolume,
        mScope=kAudioDevicePropertyScopeOutput,
        mElement=kAudioObjectPropertyElementMain
    )
    
    # 检查属性是否存在
    if not coreaudio.AudioObjectHasProperty(device_id, byref(addr)):
        raise RuntimeError(f"设备 {device_id} 不支持 VirtualMainVolume 属性")
    
    volume = c_float(0.0)
    data_size = c_uint32(ctypes.sizeof(volume))
    
    start_time = time.perf_counter()
    result = coreaudio.AudioObjectGetPropertyData(
        device_id, byref(addr), 0, None, byref(data_size), byref(volume)
    )
    elapsed = (time.perf_counter() - start_time) * 1000
    
    if result != kAudioHardwareNoError:
        raise RuntimeError(f"获取音量失败: {result}")
    
    print(f"[DEBUG] 读取音量完成，音量值: {volume.value:.4f}，耗时: {elapsed:.4f}ms")
    return volume.value


def set_volume(device_id, volume):
    """设置音量 (输入0.0-1.0)"""
    print(f"[DEBUG] 设置设备 {device_id} 音量为 {volume:.2f}...")
    
    addr = AudioObjectPropertyAddress(
        mSelector=kAudioHardwareServiceDeviceProperty_VirtualMainVolume,
        mScope=kAudioDevicePropertyScopeOutput,
        mElement=kAudioObjectPropertyElementMain
    )
    
    # 检查属性是否存在
    if not coreaudio.AudioObjectHasProperty(device_id, byref(addr)):
        raise RuntimeError(f"设备 {device_id} 不支持 VirtualMainVolume 属性")
    
    # 检查属性是否可设置
    is_settable = c_bool(False)
    result = coreaudio.AudioObjectIsPropertySettable(device_id, byref(addr), byref(is_settable))
    
    if result != kAudioHardwareNoError:
        raise RuntimeError(f"检查属性可设置性失败: {result}")
    
    if not is_settable.value:
        raise RuntimeError(f"属性不可设置")
    
    volume_val = c_float(max(0.0, min(1.0, volume)))
    data_size = c_uint32(ctypes.sizeof(volume_val))
    
    start_time = time.perf_counter()
    result = coreaudio.AudioObjectSetPropertyData(
        device_id, byref(addr), 0, None, data_size, byref(volume_val)
    )
    elapsed = (time.perf_counter() - start_time) * 1000
    
    if result != kAudioHardwareNoError:
        raise RuntimeError(f"设置音量失败: {result}")
    
    print(f"[DEBUG] 设置音量完成，耗时: {elapsed:.4f}ms")


# ============ 主程序 ============

if __name__ == '__main__':
    total_start = time.perf_counter()
    print("\n" + "=" * 50)
    print("音量检查脚本启动")
    print("=" * 50)
    
    try:
        # 1. 获取设备ID
        device_id = get_default_output_device()
        print(f"[INFO] 默认输出设备ID: {device_id}")
        
        # 2. 读取当前音量
        current_volume = get_volume(device_id)
        current_percent = int(current_volume * 100)
        
        print(f"\n{'=' * 50}")
        print(f"[结果] 当前音量: {current_percent}%")
        print(f"{'=' * 50}\n")
        
        # 3. 判断是否需要调整
        if current_percent > 90:
            print("[操作] 音量 > 90%，正在调整为 20%...")
            set_volume(device_id, 0.2)
            
            # 4. 验证
            verify_volume = get_volume(device_id)
            verify_percent = int(verify_volume * 100)
            print(f"\n[验证] 调整后音量: {verify_percent}%")
            print("[完成] 音量调整成功！")
        else:
            print("[操作] 音量 ≤ 90%，无需调整")
            
    except Exception as e:
        print(f"\n[错误] {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    total_elapsed = (time.perf_counter() - total_start) * 1000
    print(f"\n[性能] 总耗时: {total_elapsed:.3f}ms")
    print(f"[性能] 理论上1秒可执行: {1000/total_elapsed:.0f} 次")
