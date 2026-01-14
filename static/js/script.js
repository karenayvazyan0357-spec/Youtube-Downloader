document.addEventListener('DOMContentLoaded', function() {
    // Элементы DOM
    const videoUrlInput = document.getElementById('videoUrl');
    const getInfoBtn = document.getElementById('getInfoBtn');
    const downloadBtn = document.getElementById('downloadBtn');
    const videoInfoDiv = document.getElementById('videoInfo');
    const downloadProgressDiv = document.getElementById('downloadProgress');
    const errorMessageDiv = document.getElementById('errorMessage');
    const cleanupBtn = document.getElementById('cleanupBtn');
    
    // Переменные состояния
    let currentVideoInfo = null;
    let currentDownloadId = null;
    let selectedQuality = null;
    let statusCheckInterval = null;

    // Получение информации о видео
    getInfoBtn.addEventListener('click', async function() {
        const url = videoUrlInput.value.trim();
        
        if (!url) {
            showError('Пожалуйста, введите ссылку на видео');
            return;
        }
        
        if (!isValidYouTubeUrl(url)) {
            showError('Пожалуйста, введите корректную ссылку на YouTube');
            return;
        }
        
        try {
            showLoading();
            const response = await fetch('/get_info', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ url: url })
            });
            
            const data = await response.json();
            
            if (data.success) {
                displayVideoInfo(data);
                hideError();
            } else {
                showError(data.error || 'Ошибка при получении информации о видео');
            }
        } catch (error) {
            showError('Ошибка соединения с сервером');
        } finally {
            hideLoading();
        }
    });

    // Запуск загрузки
    downloadBtn.addEventListener('click', async function() {
        if (!currentVideoInfo || !selectedQuality) {
            showError('Выберите качество видео');
            return;
        }
        
        try {
            const response = await fetch('/download', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    url: videoUrlInput.value.trim(),
                    quality: selectedQuality
                })
            });
            
            const data = await response.json();
            
            if (data.success) {
                currentDownloadId = data.download_id;
                showDownloadProgress();
                startStatusChecking();
            } else {
                showError(data.error || 'Ошибка при запуске загрузки');
            }
        } catch (error) {
            showError('Ошибка соединения с сервером');
        }
    });

    // Очистка старых файлов
    cleanupBtn.addEventListener('click', async function(e) {
        e.preventDefault();
        
        if (confirm('Вы уверены, что хотите очистить старые файлы? Все файлы старше 24 часов будут удалены.')) {
            try {
                const response = await fetch('/cleanup', {
                    method: 'POST'
                });
                
                const data = await response.json();
                
                if (data.success) {
                    alert(data.message);
                } else {
                    alert('Ошибка при очистке файлов: ' + data.error);
                }
            } catch (error) {
                alert('Ошибка соединения с сервером');
            }
        }
    });

    // Функции для работы с UI
    function displayVideoInfo(data) {
        currentVideoInfo = data;
        
        // Заполняем информацию о видео
        document.getElementById('videoTitle').textContent = data.title;
        document.getElementById('videoAuthor').textContent = data.author;
        document.getElementById('videoLength').textContent = data.length;
        document.getElementById('videoViews').textContent = data.views;
        document.getElementById('videoThumbnail').src = data.thumbnail;
        
        // Создаем опции качества
        const qualityOptionsDiv = document.getElementById('qualityOptions');
        qualityOptionsDiv.innerHTML = '';
        
        data.qualities.forEach((quality, index) => {
            const optionDiv = document.createElement('div');
            optionDiv.className = 'quality-option';
            if (index === 0) {
                optionDiv.classList.add('selected');
                selectedQuality = quality.value;
            }
            
            optionDiv.innerHTML = `
                <div>
                    <strong>${quality.label}</strong>
                    <div style="font-size: 12px; color: #666; margin-top: 5px;">
                        ${quality.type === 'audio' ? 'Только аудио' : 'Видео с аудио'}
                    </div>
                </div>
            `;
            
            optionDiv.addEventListener('click', () => {
                // Снимаем выделение со всех опций
                document.querySelectorAll('.quality-option').forEach(el => {
                    el.classList.remove('selected');
                });
                
                // Выделяем выбранную опцию
                optionDiv.classList.add('selected');
                selectedQuality = quality.value;
            });
            
            qualityOptionsDiv.appendChild(optionDiv);
        });
        
        // Показываем секцию с информацией и кнопку загрузки
        videoInfoDiv.classList.remove('hidden');
        downloadBtn.classList.remove('hidden');
        
        // Прокручиваем к информации о видео
        videoInfoDiv.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }

    function showDownloadProgress() {
        downloadProgressDiv.classList.remove('hidden');
        videoInfoDiv.classList.add('hidden');
        
        // Прокручиваем к прогрессу загрузки
        downloadProgressDiv.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }

    function startStatusChecking() {
        if (statusCheckInterval) {
            clearInterval(statusCheckInterval);
        }
        
        statusCheckInterval = setInterval(async () => {
            try {
                const response = await fetch(`/status/${currentDownloadId}`);
                const data = await response.json();
                
                updateDownloadProgress(data);
                
                // Если загрузка завершена или произошла ошибка, останавливаем проверку
                if (data.status === 'completed' || data.status === 'error') {
                    clearInterval(statusCheckInterval);
                    
                    if (data.status === 'completed') {
                        // Показываем ссылку для скачивания
                        const downloadLink = document.getElementById('downloadLink');
                        downloadLink.href = data.download_url;
                        downloadLink.classList.remove('hidden');
                        
                        // Обновляем текст прогресса
                        document.getElementById('progressText').textContent = 'Загрузка завершена!';
                    }
                }
            } catch (error) {
                console.error('Error checking status:', error);
            }
        }, 2000); // Проверяем каждые 2 секунды
    }

    function updateDownloadProgress(data) {
        const progressFill = document.getElementById('progressFill');
        const progressText = document.getElementById('progressText');
        const downloadDetails = document.getElementById('downloadDetails');
        
        let progressPercent = 0;
        let statusText = '';
        
        switch (data.status) {
            case 'processing':
                progressPercent = 25;
                statusText = 'Получение информации о видео...';
                break;
            case 'downloading':
                progressPercent = 50;
                statusText = 'Скачивание видео...';
                break;
            case 'completed':
                progressPercent = 100;
                statusText = 'Загрузка завершена!';
                break;
            case 'error':
                progressPercent = 0;
                statusText = 'Ошибка: ' + (data.error || 'Неизвестная ошибка');
                showError(statusText);
                break;
            default:
                progressPercent = 10;
                statusText = 'Подготовка к загрузке...';
        }
        
        // Обновляем прогресс-бар
        progressFill.style.width = `${progressPercent}%`;
        progressText.textContent = statusText;
        
        // Обновляем детали загрузки
        let detailsHtml = '';
        if (data.title) detailsHtml += `<p><strong>Название:</strong> ${data.title}</p>`;
        if (data.resolution) detailsHtml += `<p><strong>Качество:</strong> ${data.resolution}</p>`;
        if (data.filesize) detailsHtml += `<p><strong>Размер:</strong> ${data.filesize.toFixed(1)} MB</p>`;
        
        downloadDetails.innerHTML = detailsHtml;
    }

    function showError(message) {
        errorMessageDiv.textContent = message;
        errorMessageDiv.classList.remove('hidden');
        errorMessageDiv.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }

    function hideError() {
        errorMessageDiv.classList.add('hidden');
    }

    function showLoading() {
        getInfoBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Загрузка...';
        getInfoBtn.disabled = true;
    }

    function hideLoading() {
        getInfoBtn.innerHTML = '<i class="fas fa-search"></i> Получить информацию';
        getInfoBtn.disabled = false;
    }

    function isValidYouTubeUrl(url) {
        const patterns = [
            /^(https?:\/\/)?(www\.)?(youtube\.com|youtu\.?be)\/.+/,
            /^https?:\/\/(www\.)?youtube\.com\/watch\?v=[\w-]+/,
            /^https?:\/\/youtu\.be\/[\w-]+/
        ];
        
        return patterns.some(pattern => pattern.test(url));
    }

    // Обработка нажатия Enter в поле ввода
    videoUrlInput.addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            getInfoBtn.click();
        }
    });
});