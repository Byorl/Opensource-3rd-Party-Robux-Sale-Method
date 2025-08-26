class AdminManager {
    constructor() {
        this.products = [];
        this.init();
    }

    async init() {
        await this.loadProducts();
        this.renderProducts();
        this.setupEventListeners();
    }

    async loadProducts() {
        try {
            const response = await fetch('config/products.json');
            const data = await response.json();
            this.products = data.products;
        } catch (error) {
            console.error('Failed to load products:', error);
            this.showMessage('Failed to load products', 'error');
        }
    }

    renderProducts() {
        const container = document.getElementById('productsList');
        if (!container) return;

        if (this.products.length === 0) {
            container.innerHTML = '<p>No products configured.</p>';
            return;
        }

        const productsHtml = this.products.map((product, index) => `
            <div class="product-item">
                <h3>${product.name}</h3>
                <p><strong>ID:</strong> ${product.id}</p>
                <p><strong>Price:</strong> <span class="price">${product.price} Robux</span></p>
                <p><strong>Duration:</strong> ${product.duration}</p>
                <p><strong>Description:</strong> ${product.description}</p>
                <p><strong>Gamepass ID:</strong> ${product.gamepassId}</p>
                <p><strong>Gamepass URL:</strong> <a href="${product.gamepassUrl}" target="_blank">${product.gamepassUrl}</a></p>
                <button class="delete-btn" onclick="adminManager.deleteProduct(${index})">Delete Product</button>
            </div>
        `).join('');

        container.innerHTML = productsHtml;
    }

    setupEventListeners() {
        const form = document.getElementById('productForm');
        if (form) {
            form.addEventListener('submit', (e) => {
                e.preventDefault();
                this.addProduct();
            });
        }
    }

    addProduct() {
        const formData = {
            id: document.getElementById('productId').value.trim(),
            name: document.getElementById('productName').value.trim(),
            price: parseInt(document.getElementById('productPrice').value),
            gamepassId: document.getElementById('gamepassId').value.trim(),
            gamepassUrl: document.getElementById('gamepassUrl').value.trim(),
            description: document.getElementById('description').value.trim(),
            duration: document.getElementById('duration').value.trim()
        };

        // Validate required fields
        for (const [key, value] of Object.entries(formData)) {
            if (!value || (key === 'price' && isNaN(value))) {
                this.showMessage(`Please fill in all fields correctly`, 'error');
                return;
            }
        }

        // Check for duplicate IDs
        if (this.products.some(p => p.id === formData.id)) {
            this.showMessage(`Product with ID "${formData.id}" already exists`, 'error');
            return;
        }

        // Add product
        this.products.push(formData);
        this.saveProducts();
        this.renderProducts();
        this.clearForm();
        this.showMessage('Product added successfully!', 'success');
    }

    deleteProduct(index) {
        if (confirm('Are you sure you want to delete this product?')) {
            const product = this.products[index];
            this.products.splice(index, 1);
            this.saveProducts();
            this.renderProducts();
            this.showMessage(`Product "${product.name}" deleted successfully!`, 'success');
        }
    }

    saveProducts() {
        const config = { products: this.products };
        const blob = new Blob([JSON.stringify(config, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        
        // Auto-download the file
        const a = document.createElement('a');
        a.href = url;
        a.download = 'products.json';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        
        this.showMessage('Configuration saved! Please replace config/products.json with the downloaded file.', 'success');
    }

    clearForm() {
        document.getElementById('productForm').reset();
    }

    showMessage(message, type) {
        // Remove existing messages
        const existingMessages = document.querySelectorAll('.success, .error');
        existingMessages.forEach(msg => msg.remove());

        // Create new message
        const messageDiv = document.createElement('div');
        messageDiv.className = type;
        messageDiv.textContent = message;
        
        // Insert at the top of the container
        const container = document.querySelector('.container');
        container.insertBefore(messageDiv, container.firstChild);

        // Auto-remove after 5 seconds
        setTimeout(() => {
            messageDiv.remove();
        }, 5000);
    }
}

function downloadConfig() {
    adminManager.saveProducts();
}

function clearUserData() {
    if (confirm('Are you sure you want to clear all user data? This will reset all issued keys and cannot be undone.')) {
        fetch('http://localhost:5000/admin/clear-user-data', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            }
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                adminManager.showMessage('User data cleared successfully!', 'success');
            } else {
                adminManager.showMessage('Failed to clear user data: ' + data.error, 'error');
            }
        })
        .catch(error => {
            adminManager.showMessage('Error: ' + error.message, 'error');
        });
    }
}

// Global instance
let adminManager;

// Initialize when page loads
document.addEventListener('DOMContentLoaded', () => {
    adminManager = new AdminManager();
});
