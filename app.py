from flask import Flask, render_template, request, send_file, jsonify
from pytubefix import YouTube
import os
import threading
import time
from datetime import datetime
import json
import ssl
import subprocess
import shutil

# Исправление проблемы с SSL сертификатами на macOS
# Это отключает проверку SSL сертификатов (для разработки)
ssl._create_default_https_context = ssl._create_unverified_context

app = Flask(__name__)

# Конфигурация
app.config['DOWNLOAD_FOLDER'] = 'downloads'
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB limit
app.config['SECRET_KEY'] = 'your-secret-key-change-this'

# Создаем папку для загрузок
if not os.path.exists(app.config['DOWNLOAD_FOLDER']):
    os.makedirs(app.config['DOWNLOAD_FOLDER'])

# Хранилище для статуса загрузок
download_status = {}

def merge_video_audio(video_path, audio_path, output_path):
    """Объединяет видео и аудио потоки через ffmpeg"""
    try:
        # Проверяем, что входные файлы существуют
        if not os.path.exists(video_path):
            raise Exception(f"Видео файл не найден: {video_path}")
        if not os.path.exists(audio_path):
            raise Exception(f"Аудио файл не найден: {audio_path}")
        
        # Команда ffmpeg для объединения
        cmd = [
            'ffmpeg',
            '-i', video_path,
            '-i', audio_path,
            '-c:v', 'copy',  # Копируем видео без перекодирования
            '-c:a', 'copy',  # Копируем аудио без перекодирования
            '-y',  # Перезаписывать выходной файл если существует
            '-loglevel', 'error',  # Только ошибки
            output_path
        ]
        
        # Запускаем ffmpeg
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            timeout=300  # Таймаут 5 минут
        )
        
        # Проверяем, что выходной файл создан
        if not os.path.exists(output_path):
            raise Exception("Выходной файл не был создан")
        
        # Удаляем временные файлы
        try:
            if os.path.exists(video_path):
                os.remove(video_path)
            if os.path.exists(audio_path):
                os.remove(audio_path)
        except:
            pass  # Игнорируем ошибки при удалении временных файлов
        
        return True
    except subprocess.TimeoutExpired:
        print("Таймаут при объединении видео и аудио")
        return False
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.decode() if e.stderr else str(e)
        print(f"Ошибка ffmpeg: {error_msg}")
        # Пытаемся удалить временные файлы даже при ошибке
        try:
            if os.path.exists(video_path):
                os.remove(video_path)
            if os.path.exists(audio_path):
                os.remove(audio_path)
        except:
            pass
        return False
    except Exception as e:
        print(f"Ошибка при объединении: {str(e)}")
        # Пытаемся удалить временные файлы даже при ошибке
        try:
            if os.path.exists(video_path):
                os.remove(video_path)
            if os.path.exists(audio_path):
                os.remove(audio_path)
        except:
            pass
        return False

def download_video_background(url, quality, download_id):
    """Фоновая загрузка видео"""
    try:
        yt = YouTube(url)
        
        # Получаем информацию о видео
        video_info = {
            'title': yt.title,
            'author': yt.author,
            'length': yt.length,
            'views': yt.views,
            'thumbnail': yt.thumbnail_url,
            'status': 'processing'
        }
        
        download_status[download_id] = video_info
        
        # Выбираем поток в зависимости от качества
        stream = None
        file_extension = 'mp4'
        
        if quality == 'highest':
            # Сначала пробуем progressive потоки
            progressive_streams = yt.streams.filter(progressive=True)
            adaptive_video_streams = yt.streams.filter(adaptive=True, only_video=True)
            adaptive_audio_streams = yt.streams.filter(adaptive=True, only_audio=True)
            
            # Выбираем лучший progressive поток
            best_progressive = None
            if progressive_streams:
                sorted_progressive = sorted([s for s in progressive_streams if s.resolution], 
                                          key=lambda x: int(x.resolution.replace('p', '')) if x.resolution and 'p' in x.resolution else 0,
                                          reverse=True)
                if sorted_progressive:
                    best_progressive = sorted_progressive[0]
            
            # Выбираем лучший adaptive поток
            best_adaptive_video = None
            best_adaptive_audio = None
            if adaptive_video_streams and adaptive_audio_streams:
                sorted_adaptive_video = sorted([s for s in adaptive_video_streams if s.resolution], 
                                              key=lambda x: int(x.resolution.replace('p', '')) if x.resolution and 'p' in x.resolution else 0,
                                              reverse=True)
                sorted_adaptive_audio = sorted([s for s in adaptive_audio_streams if hasattr(s, 'abr')], 
                                             key=lambda x: int(str(x.abr).replace('kbps', '')) if hasattr(x, 'abr') and 'kbps' in str(x.abr) else 0,
                                             reverse=True)
                if sorted_adaptive_video:
                    best_adaptive_video = sorted_adaptive_video[0]
                if sorted_adaptive_audio:
                    best_adaptive_audio = sorted_adaptive_audio[0]
            
            # Сравниваем качество и выбираем лучший вариант
            use_adaptive = False
            if best_adaptive_video and best_adaptive_audio:
                adaptive_res = int(best_adaptive_video.resolution.replace('p', '')) if best_adaptive_video.resolution and 'p' in best_adaptive_video.resolution else 0
                progressive_res = int(best_progressive.resolution.replace('p', '')) if best_progressive and best_progressive.resolution and 'p' in best_progressive.resolution else 0
                if adaptive_res > progressive_res:
                    use_adaptive = True
            
            if use_adaptive:
                # Используем adaptive потоки с объединением
                stream = None  # Будем обрабатывать отдельно
                video_info['use_adaptive'] = True
                video_info['adaptive_video'] = best_adaptive_video
                video_info['adaptive_audio'] = best_adaptive_audio
            else:
                # Используем progressive поток
                stream = best_progressive if best_progressive else yt.streams.get_highest_resolution()
                video_info['use_adaptive'] = False
        elif quality == 'lowest':
            stream = yt.streams.filter(progressive=True).get_lowest_resolution()
        elif quality == 'audio':
            audio_all = yt.streams.filter(only_audio=True)
            if audio_all:
                # Сортируем по битрейту
                sorted_audio = sorted([s for s in audio_all if hasattr(s, 'abr')], 
                                     key=lambda x: int(x.abr.replace('kbps', '')) if hasattr(x, 'abr') and 'kbps' in str(x.abr) else 0,
                                     reverse=True)
                stream = sorted_audio[0] if sorted_audio else audio_all.first()
            else:
                stream = yt.streams.get_audio_only()
            if stream:
                file_extension = stream.subtype if hasattr(stream, 'subtype') else 'webm'
        else:
            # Для конкретного разрешения - сначала пробуем progressive, потом adaptive
            stream = None
            use_adaptive = False
            
            # Ищем progressive поток с точным разрешением
            for s in yt.streams.filter(progressive=True):
                if s.resolution == quality:
                    stream = s
                    break
            
            # Если не нашли progressive, пробуем adaptive
            if not stream:
                adaptive_video = yt.streams.filter(res=quality, adaptive=True, only_video=True).first()
                adaptive_audio = yt.streams.filter(adaptive=True, only_audio=True).order_by('abr').desc().first()
                
                if adaptive_video and adaptive_audio:
                    use_adaptive = True
                    video_info['use_adaptive'] = True
                    video_info['adaptive_video'] = adaptive_video
                    video_info['adaptive_audio'] = adaptive_audio
                else:
                    # Если не нашли точное совпадение, ищем ближайшее большее разрешение в progressive
                    all_progressive = list(yt.streams.filter(progressive=True))
                    sorted_progressive = sorted([s for s in all_progressive if s.resolution], 
                                              key=lambda x: int(x.resolution.replace('p', '')) if x.resolution and 'p' in x.resolution else 0)
                    target_res = int(quality.replace('p', '')) if 'p' in quality else 0
                    for s in sorted_progressive:
                        res_num = int(s.resolution.replace('p', '')) if s.resolution and 'p' in s.resolution else 0
                        if res_num >= target_res:
                            stream = s
                            break
                    
                    # Если не нашли большее, берем максимальное доступное
                    if not stream and sorted_progressive:
                        stream = sorted_progressive[-1]
            else:
                video_info['use_adaptive'] = False
        
        # Обрабатываем скачивание в зависимости от типа потока
        filename_base = f"{download_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        file_extension = 'mp4'
        
        if video_info.get('use_adaptive') and video_info.get('adaptive_video') and video_info.get('adaptive_audio'):
            # Скачиваем adaptive потоки и объединяем через ffmpeg
            adaptive_video = video_info['adaptive_video']
            adaptive_audio = video_info['adaptive_audio']
            
            # Обновляем информацию о размере
            video_size = adaptive_video.filesize / (1024 * 1024) if adaptive_video.filesize else 0
            audio_size = adaptive_audio.filesize / (1024 * 1024) if adaptive_audio.filesize else 0
            video_info['filesize'] = video_size + audio_size
            video_info['resolution'] = adaptive_video.resolution if hasattr(adaptive_video, 'resolution') else 'Unknown'
            
            # Определяем расширение
            if hasattr(adaptive_video, 'subtype') and adaptive_video.subtype:
                file_extension = adaptive_video.subtype
            else:
                file_extension = 'mp4'
            
            # Скачиваем видео и аудио потоки
            video_path = adaptive_video.download(
                output_path=app.config['DOWNLOAD_FOLDER'],
                filename=f"{filename_base}_video"
            )
            audio_path = adaptive_audio.download(
                output_path=app.config['DOWNLOAD_FOLDER'],
                filename=f"{filename_base}_audio"
            )
            
            # Объединяем через ffmpeg
            output_path = os.path.join(app.config['DOWNLOAD_FOLDER'], f"{filename_base}.{file_extension}")
            if merge_video_audio(video_path, audio_path, output_path):
                filepath = output_path
            else:
                raise Exception("Не удалось объединить видео и аудио потоки")
            
            # Удаляем объекты Stream из video_info (они не сериализуются в JSON)
            if 'adaptive_video' in video_info:
                del video_info['adaptive_video']
            if 'adaptive_audio' in video_info:
                del video_info['adaptive_audio']
        else:
            # Скачиваем progressive поток
            if not stream:
                raise Exception("Не удалось найти подходящий поток для скачивания")
            
            # Обновляем информацию о размере
            video_info['filesize'] = stream.filesize / (1024 * 1024) if stream.filesize else 0
            video_info['resolution'] = stream.resolution if hasattr(stream, 'resolution') else 'audio'
            
            # Определяем расширение файла из потока
            if hasattr(stream, 'subtype') and stream.subtype:
                file_extension = stream.subtype
            elif hasattr(stream, 'mime_type'):
                mime = stream.mime_type
                if 'mp4' in mime:
                    file_extension = 'mp4'
                elif 'webm' in mime:
                    file_extension = 'webm'
                elif quality == 'audio':
                    file_extension = 'webm'
                else:
                    file_extension = 'mp4'
            elif quality == 'audio':
                file_extension = 'webm'
            else:
                file_extension = 'mp4'
            
            # Скачиваем файл
            filepath = stream.download(
                output_path=app.config['DOWNLOAD_FOLDER'],
                filename=filename_base
            )
            
            # Проверяем расширение скачанного файла
            actual_extension = os.path.splitext(filepath)[1].lstrip('.')
            
            # Если расширение не совпадает или отсутствует, переименовываем
            if not actual_extension or actual_extension != file_extension:
                new_filepath = os.path.splitext(filepath)[0] + f'.{file_extension}'
                if os.path.exists(filepath):
                    if os.path.exists(new_filepath) and new_filepath != filepath:
                        os.remove(new_filepath)
                    os.rename(filepath, new_filepath)
                    filepath = new_filepath
                elif not os.path.exists(filepath):
                    possible_path = os.path.join(app.config['DOWNLOAD_FOLDER'], filename_base)
                    if os.path.exists(possible_path):
                        new_filepath = possible_path + f'.{file_extension}'
                        if os.path.exists(new_filepath) and new_filepath != possible_path:
                            os.remove(new_filepath)
                        os.rename(possible_path, new_filepath)
                        filepath = new_filepath
        
        # Обновляем статус
        video_info['status'] = 'completed'
        video_info['filepath'] = filepath
        video_info['filename'] = os.path.basename(filepath)
        
    except Exception as e:
        if download_id in download_status:
            download_status[download_id]['status'] = 'error'
            download_status[download_id]['error'] = str(e)

@app.route('/')
def index():
    """Главная страница"""
    return render_template('index.html')

@app.route('/get_info', methods=['POST'])
def get_video_info():
    """Получение информации о видео"""
    try:
        url = request.json.get('url')
        if not url:
            return jsonify({'error': 'URL is required'}), 400
        
        yt = YouTube(url)
        
        # Получаем все доступные потоки
        progressive_streams = yt.streams.filter(progressive=True)
        adaptive_video_streams = yt.streams.filter(adaptive=True, only_video=True)
        adaptive_audio_streams = yt.streams.filter(adaptive=True, only_audio=True)
        audio_streams = yt.streams.filter(only_audio=True)
        
        # Объединяем progressive и adaptive потоки для отображения
        all_video_streams = list(progressive_streams)
        # Добавляем adaptive потоки, которые можно объединить с аудио
        for adaptive_video in adaptive_video_streams:
            if adaptive_video.resolution and adaptive_audio_streams:
                all_video_streams.append(adaptive_video)
        
        # Формируем список доступных качеств
        qualities = []
        resolutions = set()
        
        # Сортируем все потоки по разрешению
        sorted_streams = sorted([s for s in all_video_streams if s.resolution], 
                               key=lambda x: int(x.resolution.replace('p', '')) if x.resolution and 'p' in x.resolution else 0,
                               reverse=True)
        
        for stream in sorted_streams:
            if stream.resolution and stream.resolution not in resolutions:
                resolutions.add(stream.resolution)
                filesize_mb = stream.filesize / (1024 * 1024) if stream.filesize else 0
                # Для adaptive потоков добавляем размер аудио
                is_adaptive = hasattr(stream, 'is_progressive') and not stream.is_progressive
                if is_adaptive and adaptive_audio_streams:
                    best_audio = sorted([s for s in adaptive_audio_streams if hasattr(s, 'abr')], 
                                       key=lambda x: int(str(x.abr).replace('kbps', '')) if hasattr(x, 'abr') and 'kbps' in str(x.abr) else 0,
                                       reverse=True)
                    if best_audio:
                        audio_size = best_audio[0].filesize / (1024 * 1024) if best_audio[0].filesize else 0
                        filesize_mb += audio_size
                
                # Определяем тип потока
                stream_type = 'adaptive' if hasattr(stream, 'is_progressive') and not stream.is_progressive else 'progressive'
                quality_label = f"Video ({stream.resolution})"
                if stream_type == 'adaptive':
                    quality_label += " [HD]"
                quality_label += f" - {filesize_mb:.1f}MB"
                
                qualities.append({
                    'value': stream.resolution,
                    'label': quality_label,
                    'type': 'video',
                    'stream_type': stream_type
                })
        
        # Добавляем аудио опции
        if audio_streams:
            sorted_audio = sorted([s for s in audio_streams if hasattr(s, 'abr')], 
                                 key=lambda x: int(str(x.abr).replace('kbps', '')) if hasattr(x, 'abr') and 'kbps' in str(x.abr) else 0,
                                 reverse=True)
            audio = sorted_audio[0] if sorted_audio else audio_streams.first()
            if audio:
                audio_filesize_mb = audio.filesize / (1024 * 1024) if audio.filesize else 0
                audio_format = audio.subtype if hasattr(audio, 'subtype') else 'webm'
                qualities.append({
                    'value': 'audio',
                    'label': f"Audio Only ({audio_format.upper()}) - {audio_filesize_mb:.1f}MB",
                    'type': 'audio'
                })
        
        # Добавляем опции для максимального и минимального качества
        if all_video_streams:
            # Для highest используем лучший поток из всех доступных (progressive или adaptive)
            highest_sorted = sorted([s for s in all_video_streams if s.resolution], 
                                   key=lambda x: int(x.resolution.replace('p', '')) if x.resolution and 'p' in x.resolution else 0,
                                   reverse=True)
            highest = highest_sorted[0] if highest_sorted else None
            if not highest and progressive_streams:
                highest = progressive_streams.get_highest_resolution()
            
            # Для lowest используем только progressive потоки (они проще для скачивания)
            lowest_sorted = sorted([s for s in progressive_streams if s.resolution], 
                                 key=lambda x: int(x.resolution.replace('p', '')) if x.resolution and 'p' in x.resolution else 9999)
            lowest = lowest_sorted[0] if lowest_sorted else None
            if not lowest and progressive_streams:
                lowest = progressive_streams.get_lowest_resolution()
            
            if highest:
                highest_filesize_mb = highest.filesize / (1024 * 1024) if highest.filesize else 0
                # Для adaptive добавляем размер аудио
                highest_is_adaptive = hasattr(highest, 'is_progressive') and not highest.is_progressive
                if highest_is_adaptive and adaptive_audio_streams:
                    best_audio = sorted([s for s in adaptive_audio_streams if hasattr(s, 'abr')], 
                                      key=lambda x: int(str(x.abr).replace('kbps', '')) if hasattr(x, 'abr') and 'kbps' in str(x.abr) else 0,
                                      reverse=True)
                    if best_audio:
                        audio_size = best_audio[0].filesize / (1024 * 1024) if best_audio[0].filesize else 0
                        highest_filesize_mb += audio_size
                
                highest_res = highest.resolution if highest.resolution else 'Unknown'
                stream_type = 'adaptive' if highest_is_adaptive else 'progressive'
                quality_label = f"Highest Quality ({highest_res})"
                if stream_type == 'adaptive':
                    quality_label += " [HD]"
                quality_label += f" - {highest_filesize_mb:.1f}MB"
                
                qualities.insert(0, {
                    'value': 'highest',
                    'label': quality_label,
                    'type': 'video',
                    'stream_type': stream_type
                })
            
            if lowest:
                lowest_filesize_mb = lowest.filesize / (1024 * 1024) if lowest.filesize else 0
                lowest_res = lowest.resolution if lowest.resolution else 'Unknown'
                qualities.append({
                    'value': 'lowest',
                    'label': f"Lowest Quality ({lowest_res}) - {lowest_filesize_mb:.1f}MB",
                    'type': 'video',
                    'stream_type': 'progressive'
                })
        
        return jsonify({
            'title': yt.title,
            'author': yt.author,
            'length': str(yt.length // 60) + ":" + str(yt.length % 60).zfill(2),
            'views': f"{yt.views:,}",
            'thumbnail': yt.thumbnail_url,
            'qualities': qualities,
            'success': True
        })
        
    except Exception as e:
        return jsonify({'error': str(e), 'success': False}), 400

@app.route('/download', methods=['POST'])
def download_video():
    """Запуск загрузки видео"""
    try:
        url = request.json.get('url')
        quality = request.json.get('quality', 'highest')
        
        if not url:
            return jsonify({'error': 'URL is required'}), 400
        
        # Генерируем уникальный ID для загрузки
        download_id = f"dl_{int(time.time())}_{hash(url) % 10000}"
        
        # Запускаем загрузку в фоновом потоке
        thread = threading.Thread(
            target=download_video_background,
            args=(url, quality, download_id)
        )
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'download_id': download_id,
            'message': 'Download started',
            'success': True
        })
        
    except Exception as e:
        return jsonify({'error': str(e), 'success': False}), 400

@app.route('/status/<download_id>')
def get_download_status(download_id):
    """Проверка статуса загрузки"""
    if download_id in download_status:
        status = download_status[download_id].copy()
        
        # Удаляем объекты Stream, которые не могут быть сериализованы в JSON
        if 'adaptive_video' in status:
            del status['adaptive_video']
        if 'adaptive_audio' in status:
            del status['adaptive_audio']
        
        # Если загрузка завершена, добавляем ссылку для скачивания
        if status.get('status') == 'completed':
            status['download_url'] = f"/download_file/{status['filename']}"
        
        return jsonify(status)
    else:
        return jsonify({'error': 'Download not found'}), 404

@app.route('/download_file/<filename>')
def download_file(filename):
    """Скачивание готового файла"""
    try:
        filepath = os.path.join(app.config['DOWNLOAD_FOLDER'], filename)
        
        if not os.path.exists(filepath):
            return "File not found", 404
        
        # Определяем тип контента
        if filename.endswith('.mp4'):
            mimetype = 'video/mp4'
        elif filename.endswith('.webm'):
            mimetype = 'video/webm'
        elif filename.endswith('.mp3'):
            mimetype = 'audio/mpeg'
        else:
            mimetype = 'application/octet-stream'
        
        return send_file(
            filepath,
            as_attachment=True,
            download_name=filename.split('_', 1)[-1] if '_' in filename else filename,
            mimetype=mimetype
        )
        
    except Exception as e:
        return str(e), 500

@app.route('/cleanup', methods=['POST'])
def cleanup_old_files():
    """Очистка старых файлов (опционально)"""
    try:
        # Удаляем файлы старше 24 часов
        import time
        current_time = time.time()
        deleted_files = []
        
        for filename in os.listdir(app.config['DOWNLOAD_FOLDER']):
            filepath = os.path.join(app.config['DOWNLOAD_FOLDER'], filename)
            file_age = current_time - os.path.getmtime(filepath)
            
            if file_age > 24 * 3600:  # 24 часа
                os.remove(filepath)
                deleted_files.append(filename)
        
        # Очищаем старые статусы
        global download_status
        download_status = {k: v for k, v in download_status.items() 
                          if v.get('status') != 'completed' or 
                          'filepath' in v and os.path.exists(v['filepath'])}
        
        return jsonify({
            'message': f'Cleaned up {len(deleted_files)} old files',
            'deleted_files': deleted_files,
            'success': True
        })
        
    except Exception as e:
        return jsonify({'error': str(e), 'success': False}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)