// Offline Manager
class OfflineManager {
    constructor() {
        this.queue = this.loadQueue();
        this.setupEventListeners();
        this.processQueue();
    }

    loadQueue() {
        const saved = localStorage.getItem('offlineQueue');
        return saved ? JSON.parse(saved) : [];
    }

    saveQueue() {
        localStorage.setItem('offlineQueue', JSON.stringify(this.queue));
    }

    queueRequest(method, url, data) {
        const request = {
            id: Date.now(),
            method,
            url,
            data,
            timestamp: new Date().toISOString()
        };
        this.queue.push(request);
        this.saveQueue();
        console.log('Request queued for offline sync:', request);
        return request.id;
    }

    setupEventListeners() {
        window.addEventListener('online', () => {
            console.log('Back online, processing queue...');
            this.processQueue();
        });
    }

    async processQueue() {
        if (!navigator.onLine) return;
        
        const queue = [...this.queue];
        for (const request of queue) {
            try {
                const response = await fetch(request.url, {
                    method: request.method,
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.getCookie('csrftoken')
                    },
                    body: request.data ? JSON.stringify(request.data) : null
                });
                
                if (response.ok) {
                    this.queue = this.queue.filter(r => r.id !== request.id);
                    this.saveQueue();
                    console.log('Queued request processed:', request);
                }
            } catch (error) {
                console.error('Failed to process queued request:', error);
            }
        }
    }

    getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }
}

// Initialize offline manager
window.offlineManager = new OfflineManager();
