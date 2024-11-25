async function validatePurchase() {
    const username = document.getElementById('username').value.trim();

    if (!username) {
        alert('Please enter your username.');
        return;
    }

    // Hide the priceInfo and purchaseTitle
    const priceInfoElement = document.querySelector('.priceInfo');
    const purchaseTitleElement = document.querySelector('.purchaseTitle');

    if (priceInfoElement) priceInfoElement.style.display = 'none';
    if (purchaseTitleElement) purchaseTitleElement.style.display = 'none';

    // Hide the username input and continue button
    ['username', 'continueButton', 'usernameLabel'].forEach(id => {
        const element = document.getElementById(id);
        if (element) element.style.display = 'none';
    });

    const statusElement = document.getElementById('status');
    updateStatus(statusElement, 'Verifying Purchase... (This may take a minute)', 'gray');

    try {
        await checkGamepassAndIssueKey(username);
    } catch (error) {
        handleValidationError(statusElement, error);
    }
}

async function checkGamepassAndIssueKey(username, gamepassId = '7day-gamepass-id') {
    const statusElement = document.getElementById('status');

    try {
        const response = await fetchGamepassCheck(username, gamepassId);

        if (response.hasGamePass) {
            if (response.keyIssued) {
                updateStatus(statusElement, 'Purchase Completed!', 'green');
                displayKey(response.key);
            } else {
                updateStatus(statusElement, response.message, 'red');
                // Show retry option for expired key
                displayRetryOption(username, gamepassId);
            }
        } else {
            updateStatus(statusElement, 'Gamepass not owned. Redirecting to purchase...', 'red');
            window.open(response.gamepassLink, '_blank');
            // Start verification process after redirect
            await startPurchaseVerification(username, gamepassId);
        }
    } catch (error) {
        handleValidationError(statusElement, error);
    }
}

async function startPurchaseVerification(username, gamepassId) {
    const statusElement = document.getElementById('status');
    updateStatus(statusElement, 'Verifying Purchase... (This may take a minute)', 'gray');

    return new Promise((resolve, reject) => {
        const checkInterval = setInterval(async () => {
            try {
                const response = await fetchGamepassCheck(username, gamepassId);

                if (response.hasGamePass) {
                    if (response.keyIssued) {
                        clearInterval(checkInterval);
                        updateStatus(statusElement, 'Purchase Completed!', 'green');
                        displayKey(response.key);
                        resolve();
                    } else {
                        const message = gamepassId === '7day-gamepass-id' 
                            ? '7-day key already claimed' 
                            : '30-day key already claimed';
                        updateStatus(statusElement, message, 'red');
                        clearInterval(checkInterval);
                        resolve();
                    }
                }
            } catch (error) {
                clearInterval(checkInterval);
                handleValidationError(statusElement, error);
                reject(error);
            }
        }, 5000);

        // Stop checking after 5 minutes
        setTimeout(() => {
            clearInterval(checkInterval);
            updateStatus(statusElement, 'Purchase verification timed out. Please try again.', 'red');
            reject(new Error('Verification timeout'));
        }, 300000);
    });
}

async function requestNewKey(username, gamepassId) {
    const statusElement = document.getElementById('status');

    try {
        const response = await fetchGamepassCheck(username, gamepassId);
        if (response.keyIssued) {
            updateStatus(statusElement, `Key issued successfully! Here's your key:`, 'green');
            displayKey(response.key);
        } else {
            const message = gamepassId === '7day-gamepass-id'
                ? 'You have already claimed the 7-day key. To get a new key, please remove the gamepass and repurchase.'
                : 'You have already claimed the 30-day key. To get a new key, please remove the gamepass and repurchase.';
            updateStatus(statusElement, message, 'red');
        }
    } catch (error) {
        handleValidationError(statusElement, error);
    }
}

async function fetchGamepassCheck(username, gamepassId) {
    try {
        const response = await fetch('http://localhost:5000/check-gamepass', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ username, gamepass_id: gamepassId })
        });

        if (response.status === 429) {
            console.log('Rate limit hit, waiting...');
            await new Promise(resolve => setTimeout(resolve, 15000 * Math.random() + 5000));
            return await fetchGamepassCheck(username, gamepassId);
        }

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.error || 'Failed to check gamepass');
        }

        const responseData = await response.json();
        return responseData;
    } catch (error) {
        console.error('Fetch error:', error);
        throw error;
    }
}

function displayKey(key) {
    const keyContainer = document.getElementById('keyContainer');
    const keyElement = document.getElementById('key');
    keyElement.value = key;
    keyContainer.style.display = 'block';
}

function displayRetryOption(username, gamepassId) {
    const statusElement = document.getElementById('status');
    const retryContainer = document.createElement('div');
    retryContainer.style.marginTop = '20px';
    
    const message = document.createElement('p');
    message.innerText = '   To get a new key, please:';
    
    const steps = document.createElement('ol');
    steps.innerHTML = `
        <li>Remove the gamepass from your Roblox inventory</li>
        <li>Return to this page</li>
        <li>Re-Purchase the gamepass</li>
    `;
    
    const retryButton = document.createElement('button');
    retryButton.innerText = 'I have removed the gamepass. Check again';
    retryButton.onclick = () => checkGamepassAndIssueKey(username, gamepassId);
    retryButton.style.marginTop = '10px';
    
    retryContainer.appendChild(message);
    retryContainer.appendChild(steps);
    retryContainer.appendChild(retryButton);
    statusElement.appendChild(retryContainer);
}

function updateStatus(statusElement, message, color) {
    statusElement.innerText = message;
    statusElement.style.color = color;
    statusElement.style.textAlign = 'center';
}

function handleValidationError(statusElement, error) {
    console.error('Validation error:', error);
    updateStatus(statusElement, `Error: ${error.message}`, 'red');

    const retryButton = document.createElement('button');
    retryButton.innerText = 'Try Again';
    retryButton.onclick = () => window.location.reload();
    retryButton.style.marginTop = '10px';
    statusElement.appendChild(retryButton);
}
